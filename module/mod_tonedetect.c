/*
 * mod_tonedetect.c -- FreeSWITCH call-progress (ringback) tone detector.
 *
 * Phase 1: local DSP detection of China-450Hz signal tones
 * (ringback / busy / congestion / 450hz / silence / other) from early media.
 *
 * Usage (dialplan / originate):
 *   originate {execute_on_pre_answer=start_tonedetect,ignore_early_media=consume}sofia/gateway/NUM &park
 *
 * Results are exposed on the channel:
 *   tonedetect_tone          last/best tone type (ringback|busy|congestion|450hz|silence|other)
 *   tonedetect_finish_cause  why detection stopped (stoptone|timeout|hangup|stop)
 * and via a CUSTOM event with subclass "tonedetect".
 *
 * Channel-variable overrides (read at start):
 *   tonedetect_stoptone      space/comma list: busy ringback congestion 450hz silence other all
 *   tonedetect_autohangup    true|false
 *   tonedetect_maxdetecttime seconds
 */
#include <switch.h>
#include "tone_dsp.h"
#include "ws_client.h"

SWITCH_MODULE_LOAD_FUNCTION(mod_tonedetect_load);
SWITCH_MODULE_SHUTDOWN_FUNCTION(mod_tonedetect_shutdown);
SWITCH_MODULE_DEFINITION(mod_tonedetect, mod_tonedetect_load, mod_tonedetect_shutdown, NULL);

#define TONEDETECT_EVENT_SUBCLASS "tonedetect"
#define TONEDETECT_BUG_NAME "tonedetect"
#define TONEDETECT_PRIVATE "_tonedetect_"

/* tone bitmask (stoptone set) */
#define TD_BUSY       0x01
#define TD_RINGBACK   0x02
#define TD_CONGESTION 0x04
#define TD_OTHER      0x08
#define TD_450HZ      0x10
#define TD_SILENCE    0x20
#define TD_ALL        0x3f

static struct {
	uint32_t stoptone_mask;
	int autohangup;
	int maxdetecttime;       /* seconds */
	tone_dsp_config_t dsp;   /* default DSP tuning (rule ranges, thresholds) */
	char server_url[256];    /* phase-2: recognition service ws:// url ("" = disabled) */
	char server_key[128];    /* phase-2: auth key sent in START */
	char recordpath[256];    /* collection: dir to record early media WAV ("" = disabled) */
} globals;

typedef struct {
	switch_core_session_t *session;
	tone_dsp_t *dsp;
	uint32_t stoptone_mask;
	int autohangup;
	int maxdetecttime;
	switch_time_t start_time;
	int stopped;
	const char *finish_cause;
	ws_client_t *ws;         /* phase-2: streaming client (NULL = disabled) */
	switch_file_handle_t *rec_fh; /* collection: early-media recording (NULL = disabled) */
} td_context_t;

static uint32_t tone_to_mask(tone_type_t t)
{
	switch (t) {
	case TONE_BUSY:       return TD_BUSY;
	case TONE_RINGBACK:   return TD_RINGBACK;
	case TONE_CONGESTION: return TD_CONGESTION;
	case TONE_OTHER:      return TD_OTHER;
	case TONE_450HZ:      return TD_450HZ;
	case TONE_SILENCE:    return TD_SILENCE;
	default:              return 0;
	}
}

static uint32_t parse_stoptone(const char *s)
{
	uint32_t mask = 0;
	char *dup, *p, *tok, *save = NULL;

	if (zstr(s)) return 0;
	dup = strdup(s);
	if (!dup) return 0;

	for (p = dup; (tok = strtok_r(p, " ,;\t", &save)); p = NULL) {
		if (!strcasecmp(tok, "all")) mask |= TD_ALL;
		else if (!strcasecmp(tok, "busy")) mask |= TD_BUSY;
		else if (!strcasecmp(tok, "ringback")) mask |= TD_RINGBACK;
		else if (!strcasecmp(tok, "congestion")) mask |= TD_CONGESTION;
		else if (!strcasecmp(tok, "other")) mask |= TD_OTHER;
		else if (!strcasecmp(tok, "colorringback")) mask |= TD_OTHER;
		else if (!strcasecmp(tok, "450hz")) mask |= TD_450HZ;
		else if (!strcasecmp(tok, "silence")) mask |= TD_SILENCE;
	}
	free(dup);
	return mask;
}

/* DSP detection callback: runs inside the media-bug read thread. */
static void on_tone(void *user, tone_type_t type, int begin_ms, int end_ms)
{
	td_context_t *ctx = (td_context_t *) user;
	switch_channel_t *channel;
	switch_event_t *event;
	const char *name = tone_type_name(type);

	if (!ctx || !ctx->session) return;
	channel = switch_core_session_get_channel(ctx->session);

	switch_channel_set_variable(channel, "tonedetect_tone", name);

	if (switch_event_create_subclass(&event, SWITCH_EVENT_CUSTOM, TONEDETECT_EVENT_SUBCLASS) == SWITCH_STATUS_SUCCESS) {
		switch_channel_event_set_data(channel, event);
		switch_event_add_header_string(event, SWITCH_STACK_BOTTOM, "tonedetect_tone", name);
		switch_event_add_header(event, SWITCH_STACK_BOTTOM, "tonedetect_begin_ms", "%d", begin_ms);
		switch_event_add_header(event, SWITCH_STACK_BOTTOM, "tonedetect_end_ms", "%d", end_ms);
		switch_event_fire(&event);
	}

	switch_log_printf(SWITCH_CHANNEL_SESSION_LOG(ctx->session), SWITCH_LOG_DEBUG,
		"tonedetect: %s [%d-%d ms]\n", name, begin_ms, end_ms);

	if (!ctx->stopped && (tone_to_mask(type) & ctx->stoptone_mask)) {
		ctx->stopped = 1;
		ctx->finish_cause = "stoptone";
		switch_channel_set_variable(channel, "tonedetect_finish_cause", "stoptone");
		if (ctx->autohangup) {
			switch_log_printf(SWITCH_CHANNEL_SESSION_LOG(ctx->session), SWITCH_LOG_INFO,
				"tonedetect: stoptone '%s' matched, hanging up\n", name);
			switch_channel_hangup(channel, SWITCH_CAUSE_NORMAL_CLEARING);
		}
	}
}

/* Phase-2: handle a RESULT JSON pushed back by the recognition service.
 * Runs on the ws_client service thread. */
static void ws_on_result(void *user, const char *json, size_t len)
{
	td_context_t *ctx = (td_context_t *) user;
	switch_channel_t *channel;
	switch_event_t *event;
	cJSON *root, *item;
	const char *type = "", *tone = "", *accuracy = "", *alias = "", *category = "", *name = "";

	(void) len;
	if (!ctx || !ctx->session || !json) return;
	channel = switch_core_session_get_channel(ctx->session);

	root = cJSON_Parse(json);
	if (!root) return;

	if ((item = cJSON_GetObjectItem(root, "type")) && item->valuestring) type = item->valuestring;
	if (strcmp(type, "result") != 0) {
		cJSON_Delete(root);
		return;
	}
	if ((item = cJSON_GetObjectItem(root, "tone")) && item->valuestring) tone = item->valuestring;
	if ((item = cJSON_GetObjectItem(root, "accuracy")) && item->valuestring) accuracy = item->valuestring;
	if ((item = cJSON_GetObjectItem(root, "alias")) && item->valuestring) alias = item->valuestring;
	if ((item = cJSON_GetObjectItem(root, "category")) && item->valuestring) category = item->valuestring;
	if ((item = cJSON_GetObjectItem(root, "name")) && item->valuestring) name = item->valuestring;

	switch_channel_set_variable(channel, "tonedetect_da_tone", tone);
	switch_channel_set_variable(channel, "tonedetect_da_accuracy", accuracy);
	if (*alias) switch_channel_set_variable(channel, "tonedetect_da_alias", alias);
	if (*category) switch_channel_set_variable(channel, "tonedetect_da_category", category);
	if (*name) switch_channel_set_variable(channel, "tonedetect_da_name", name);

	if (switch_event_create_subclass(&event, SWITCH_EVENT_CUSTOM, TONEDETECT_EVENT_SUBCLASS) == SWITCH_STATUS_SUCCESS) {
		switch_channel_event_set_data(channel, event);
		switch_event_add_header_string(event, SWITCH_STACK_BOTTOM, "tonedetect_source", "server");
		switch_event_add_header_string(event, SWITCH_STACK_BOTTOM, "tonedetect_da_tone", tone);
		switch_event_add_header_string(event, SWITCH_STACK_BOTTOM, "tonedetect_da_accuracy", accuracy);
		if (*alias) switch_event_add_header_string(event, SWITCH_STACK_BOTTOM, "tonedetect_da_alias", alias);
		if (*category) switch_event_add_header_string(event, SWITCH_STACK_BOTTOM, "tonedetect_da_category", category);
		switch_event_fire(&event);
	}

	switch_log_printf(SWITCH_CHANNEL_SESSION_LOG(ctx->session), SWITCH_LOG_INFO,
		"tonedetect[server]: tone=%s accuracy=%s alias=%s category=%s\n", tone, accuracy, alias, category);

	/* only ACCURACY sample matches drive autohangup */
	if (!ctx->stopped && !strcmp(accuracy, "ACCURACY") && !strcmp(tone, "sample")) {
		ctx->stopped = 1;
		ctx->finish_cause = "sample";
		switch_channel_set_variable(channel, "tonedetect_finish_cause", "sample");
		if (ctx->autohangup) {
			switch_channel_hangup(channel, SWITCH_CAUSE_NORMAL_CLEARING);
		}
	}

	cJSON_Delete(root);
}

static switch_bool_t tonedetect_bug_cb(switch_media_bug_t *bug, void *user_data, switch_abc_type_t type)
{
	td_context_t *ctx = (td_context_t *) user_data;

	switch (type) {
	case SWITCH_ABC_TYPE_INIT:
		break;

	case SWITCH_ABC_TYPE_READ_REPLACE:
	{
		switch_frame_t *frame = switch_core_media_bug_get_read_replace_frame(bug);
		if (frame && frame->data && frame->samples > 0) {
			tone_dsp_process(ctx->dsp, (const int16_t *) frame->data, frame->samples);
			if (ctx->ws) {
				ws_client_send_audio(ctx->ws, (const int16_t *) frame->data, frame->samples);
			}
			if (ctx->rec_fh) {
				switch_size_t len = frame->samples;
				switch_core_file_write(ctx->rec_fh, frame->data, &len);
			}
		}
		if (ctx->maxdetecttime > 0 &&
			(switch_time_now() - ctx->start_time) > (switch_time_t) ctx->maxdetecttime * 1000000) {
			if (!ctx->stopped) {
				switch_channel_t *channel = switch_core_session_get_channel(ctx->session);
				ctx->stopped = 1;
				ctx->finish_cause = "timeout";
				switch_channel_set_variable(channel, "tonedetect_finish_cause", "timeout");
			}
			return SWITCH_FALSE; /* remove the bug */
		}
		if (ctx->stopped) {
			return SWITCH_FALSE;
		}
		break;
	}

	case SWITCH_ABC_TYPE_CLOSE:
		if (ctx->ws) {
			ws_client_send_text(ctx->ws, "{\"type\":\"stop\"}");
			ws_client_destroy(ctx->ws);
			ctx->ws = NULL;
		}
		if (ctx->rec_fh) {
			switch_core_file_close(ctx->rec_fh);
			ctx->rec_fh = NULL;
		}
		if (ctx->dsp) {
			tone_dsp_destroy(ctx->dsp);
			ctx->dsp = NULL;
		}
		break;

	default:
		break;
	}

	return SWITCH_TRUE;
}

#define START_TONEDETECT_SYNTAX ""
SWITCH_STANDARD_APP(start_tonedetect_app)
{
	switch_channel_t *channel = switch_core_session_get_channel(session);
	switch_media_bug_t *bug;
	td_context_t *ctx;
	switch_codec_implementation_t read_impl = { 0 };
	const char *var;
	tone_dsp_config_t dsp_cfg;

	if (switch_channel_get_private(channel, TONEDETECT_PRIVATE)) {
		switch_log_printf(SWITCH_CHANNEL_SESSION_LOG(session), SWITCH_LOG_WARNING,
			"tonedetect: already running on this channel\n");
		return;
	}

	ctx = switch_core_session_alloc(session, sizeof(*ctx));
	ctx->session = session;
	ctx->start_time = switch_time_now();
	ctx->stopped = 0;
	ctx->finish_cause = "stop";

	/* defaults from config, overridable via channel variables */
	ctx->stoptone_mask = globals.stoptone_mask;
	ctx->autohangup = globals.autohangup;
	ctx->maxdetecttime = globals.maxdetecttime;

	if ((var = switch_channel_get_variable(channel, "tonedetect_stoptone"))) {
		ctx->stoptone_mask = parse_stoptone(var);
	}
	if ((var = switch_channel_get_variable(channel, "tonedetect_autohangup"))) {
		ctx->autohangup = switch_true(var);
	}
	if ((var = switch_channel_get_variable(channel, "tonedetect_maxdetecttime"))) {
		ctx->maxdetecttime = atoi(var);
	}

	switch_core_session_get_read_impl(session, &read_impl);
	dsp_cfg = globals.dsp;
	if (read_impl.actual_samples_per_second > 0) {
		dsp_cfg.sample_rate = read_impl.actual_samples_per_second;
	}

	ctx->dsp = tone_dsp_create(&dsp_cfg, on_tone, ctx);
	if (!ctx->dsp) {
		switch_log_printf(SWITCH_CHANNEL_SESSION_LOG(session), SWITCH_LOG_ERROR,
			"tonedetect: failed to create detector\n");
		return;
	}

	if (switch_core_media_bug_add(session, TONEDETECT_BUG_NAME, NULL, tonedetect_bug_cb, ctx,
			0, SMBF_READ_REPLACE | SMBF_NO_PAUSE | SMBF_ONE_ONLY, &bug) != SWITCH_STATUS_SUCCESS) {
		switch_log_printf(SWITCH_CHANNEL_SESSION_LOG(session), SWITCH_LOG_ERROR,
			"tonedetect: failed to add media bug\n");
		tone_dsp_destroy(ctx->dsp);
		ctx->dsp = NULL;
		return;
	}

	switch_channel_set_private(channel, TONEDETECT_PRIVATE, bug);

	/* collection: record the early media to a WAV for sample harvesting */
	{
		const char *recordpath = switch_channel_get_variable(channel, "tonedetect_record_path");
		if (!recordpath && globals.recordpath[0]) recordpath = globals.recordpath;
		if (recordpath) {
			char path[512];
			const char *uuid = switch_core_session_get_uuid(session);
			ctx->rec_fh = switch_core_session_alloc(session, sizeof(*ctx->rec_fh));
			memset(ctx->rec_fh, 0, sizeof(*ctx->rec_fh));
			switch_snprintf(path, sizeof(path), "%s%s%s.wav", recordpath,
				SWITCH_PATH_SEPARATOR, uuid ? uuid : "tonedetect");
			if (switch_core_file_open(ctx->rec_fh, path, 1, dsp_cfg.sample_rate,
					SWITCH_FILE_FLAG_WRITE | SWITCH_FILE_DATA_SHORT,
					switch_core_session_get_pool(session)) != SWITCH_STATUS_SUCCESS) {
				ctx->rec_fh = NULL;
				switch_log_printf(SWITCH_CHANNEL_SESSION_LOG(session), SWITCH_LOG_WARNING,
					"tonedetect: failed to open record file %s\n", path);
			} else {
				switch_log_printf(SWITCH_CHANNEL_SESSION_LOG(session), SWITCH_LOG_INFO,
					"tonedetect: recording early media to %s\n", path);
			}
		}
	}

	/* phase-2: also stream audio to the recognition service if configured */
	if (globals.server_url[0]) {
		ctx->ws = ws_client_create(globals.server_url, ws_on_result, ctx);
		if (ctx->ws && ws_client_start(ctx->ws) == 0) {
			char start_json[640];
			const char *uuid = switch_core_session_get_uuid(session);
			switch_snprintf(start_json, sizeof(start_json),
				"{\"type\":\"start\",\"version\":1,\"uuid\":\"%s\",\"codec\":\"L16\",\"samplerate\":%d,\"key\":\"%s\"}",
				uuid ? uuid : "", dsp_cfg.sample_rate, globals.server_key);
			ws_client_send_text(ctx->ws, start_json);
			switch_log_printf(SWITCH_CHANNEL_SESSION_LOG(session), SWITCH_LOG_INFO,
				"tonedetect: streaming to recognition service %s\n", globals.server_url);
		} else {
			if (ctx->ws) { ws_client_destroy(ctx->ws); ctx->ws = NULL; }
			switch_log_printf(SWITCH_CHANNEL_SESSION_LOG(session), SWITCH_LOG_WARNING,
				"tonedetect: failed to connect recognition service %s (local DSP still active)\n",
				globals.server_url);
		}
	}

	switch_log_printf(SWITCH_CHANNEL_SESSION_LOG(session), SWITCH_LOG_INFO,
		"tonedetect: started (rate=%d, stoptone=0x%02x, autohangup=%d, maxdetecttime=%d)\n",
		dsp_cfg.sample_rate, ctx->stoptone_mask, ctx->autohangup, ctx->maxdetecttime);
}

SWITCH_STANDARD_APP(stop_tonedetect_app)
{
	switch_channel_t *channel = switch_core_session_get_channel(session);
	switch_media_bug_t *bug = (switch_media_bug_t *) switch_channel_get_private(channel, TONEDETECT_PRIVATE);

	if (bug) {
		switch_channel_set_private(channel, TONEDETECT_PRIVATE, NULL);
		switch_core_media_bug_remove(session, &bug);
		switch_log_printf(SWITCH_CHANNEL_SESSION_LOG(session), SWITCH_LOG_INFO, "tonedetect: stopped\n");
	}
}

static void apply_rule(const char *val, int *on_min, int *on_max, int *off_min, int *off_max)
{
	/* "on_min-on_max|off_min-off_max" */
	int a = 0, b = 0, c = 0, d = 0;
	if (zstr(val)) return;
	if (sscanf(val, "%d-%d|%d-%d", &a, &b, &c, &d) == 4) {
		*on_min = a; *on_max = b; *off_min = c; *off_max = d;
	}
}

static switch_status_t load_config(void)
{
	switch_xml_t cfg, xml, settings, param;
	const char *cf = "tonedetect.conf";

	memset(&globals, 0, sizeof(globals));
	tone_dsp_config_default(&globals.dsp);
	globals.stoptone_mask = TD_BUSY | TD_SILENCE; /* sensible default */
	globals.autohangup = 1;
	globals.maxdetecttime = 60;

	if (!(xml = switch_xml_open_cfg(cf, &cfg, NULL))) {
		switch_log_printf(SWITCH_CHANNEL_LOG, SWITCH_LOG_WARNING,
			"tonedetect: no %s, using defaults\n", cf);
		return SWITCH_STATUS_SUCCESS;
	}

	if ((settings = switch_xml_child(cfg, "settings"))) {
		for (param = switch_xml_child(settings, "param"); param; param = param->next) {
			const char *name = switch_xml_attr_soft(param, "name");
			const char *value = switch_xml_attr_soft(param, "value");

			if (!strcasecmp(name, "stoptone")) {
				globals.stoptone_mask = parse_stoptone(value);
			} else if (!strcasecmp(name, "autohangup")) {
				globals.autohangup = switch_true(value);
			} else if (!strcasecmp(name, "maxdetecttime")) {
				globals.maxdetecttime = atoi(value);
			} else if (!strcasecmp(name, "purity_threshold")) {
				globals.dsp.purity_threshold = atof(value);
			} else if (!strcasecmp(name, "silence_rms")) {
				globals.dsp.silence_rms = atof(value);
			} else if (!strcasecmp(name, "tone_busy_rule")) {
				apply_rule(value, &globals.dsp.busy_on_min, &globals.dsp.busy_on_max,
					&globals.dsp.busy_off_min, &globals.dsp.busy_off_max);
			} else if (!strcasecmp(name, "tone_congestion_rule")) {
				apply_rule(value, &globals.dsp.cong_on_min, &globals.dsp.cong_on_max,
					&globals.dsp.cong_off_min, &globals.dsp.cong_off_max);
			} else if (!strcasecmp(name, "tone_ringback_rule")) {
				apply_rule(value, &globals.dsp.ring_on_min, &globals.dsp.ring_on_max,
					&globals.dsp.ring_off_min, &globals.dsp.ring_off_max);
			} else if (!strcasecmp(name, "server_url")) {
				switch_set_string(globals.server_url, value);
			} else if (!strcasecmp(name, "server_key")) {
				switch_set_string(globals.server_key, value);
			} else if (!strcasecmp(name, "recordpath")) {
				switch_set_string(globals.recordpath, value);
			}
		}
	}

	switch_xml_free(xml);
	return SWITCH_STATUS_SUCCESS;
}

SWITCH_MODULE_LOAD_FUNCTION(mod_tonedetect_load)
{
	switch_application_interface_t *app_interface;

	*module_interface = switch_loadable_module_create_module_interface(pool, modname);

	if (switch_event_reserve_subclass(TONEDETECT_EVENT_SUBCLASS) != SWITCH_STATUS_SUCCESS) {
		switch_log_printf(SWITCH_CHANNEL_LOG, SWITCH_LOG_ERROR,
			"tonedetect: cannot reserve event subclass %s\n", TONEDETECT_EVENT_SUBCLASS);
		return SWITCH_STATUS_TERM;
	}

	load_config();

	SWITCH_ADD_APP(app_interface, "start_tonedetect", "Start call-progress tone detection",
		"Detect ringback/busy/congestion/etc on early media", start_tonedetect_app,
		START_TONEDETECT_SYNTAX, SAF_NONE);
	SWITCH_ADD_APP(app_interface, "stop_tonedetect", "Stop call-progress tone detection",
		"Stop tone detection", stop_tonedetect_app, "", SAF_NONE);

	switch_log_printf(SWITCH_CHANNEL_LOG, SWITCH_LOG_INFO, "mod_tonedetect loaded\n");
	return SWITCH_STATUS_SUCCESS;
}

SWITCH_MODULE_SHUTDOWN_FUNCTION(mod_tonedetect_shutdown)
{
	switch_event_free_subclass(TONEDETECT_EVENT_SUBCLASS);
	switch_log_printf(SWITCH_CHANNEL_LOG, SWITCH_LOG_INFO, "mod_tonedetect shutdown\n");
	return SWITCH_STATUS_SUCCESS;
}
