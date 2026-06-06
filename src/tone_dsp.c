/*
 * tone_dsp.c -- implementation of the China 450Hz call-progress tone detector.
 *
 * Pipeline:
 *   PCM samples -> fixed-size analysis blocks (block_ms) ->
 *   per-block label {TONE_450 | SILENCE | OTHER} via Goertzel + RMS ->
 *   cadence state machine -> tone classification.
 */
#include "tone_dsp.h"

#include <stdlib.h>
#include <string.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* per-block coarse label */
typedef enum {
	BLK_SILENCE = 0,
	BLK_TONE,    /* 450Hz dominant */
	BLK_OTHER    /* energy present but not 450Hz dominant */
} block_label_t;

struct tone_dsp_s {
	tone_dsp_config_t cfg;
	tone_dsp_cb cb;
	void *user;

	int block_size;        /* samples per analysis block */
	double goertzel_coeff; /* 2*cos(w) */

	/* accumulation buffer for a partial block */
	int16_t *buf;
	int buf_len;

	/* cadence state machine */
	block_label_t cur_label;
	int run_ms;            /* duration of current run */
	int last_on_ms;        /* duration of the last completed TONE run */
	int run_begin_ms;      /* stream time when current run started */
	int last_on_begin_ms;  /* stream time when last TONE run started */
	int run_reported;      /* sustained-run report already emitted for this run */

	int total_ms;          /* total stream time processed */
	tone_type_t last;      /* last reported classification */
};

void tone_dsp_config_default(tone_dsp_config_t *cfg)
{
	if (!cfg) return;
	memset(cfg, 0, sizeof(*cfg));
	cfg->sample_rate = 8000;
	cfg->target_freq = 450.0;
	cfg->block_ms = 20;
	cfg->purity_threshold = 0.40;
	cfg->silence_rms = 200.0;

	/* China tone plan (ms), with tolerance bands */
	cfg->busy_on_min = 250;  cfg->busy_on_max = 450;
	cfg->busy_off_min = 250; cfg->busy_off_max = 450;

	cfg->cong_on_min = 550;  cfg->cong_on_max = 850;
	cfg->cong_off_min = 500; cfg->cong_off_max = 850;

	cfg->ring_on_min = 800;  cfg->ring_on_max = 1300;
	cfg->ring_off_min = 3000; cfg->ring_off_max = 5000;

	cfg->ring_early_off_ms = 2000;
	cfg->min_tone_ms = 150;
	cfg->min_other_ms = 400;
	cfg->silence_min_ms = 1000;
}

static int in_range(int v, int lo, int hi)
{
	return v >= lo && v <= hi;
}

tone_dsp_t *tone_dsp_create(const tone_dsp_config_t *cfg, tone_dsp_cb cb, void *user)
{
	tone_dsp_t *d;
	tone_dsp_config_t defcfg;
	double w;

	if (!cfg) {
		tone_dsp_config_default(&defcfg);
		cfg = &defcfg;
	}

	d = (tone_dsp_t *) calloc(1, sizeof(*d));
	if (!d) return NULL;

	d->cfg = *cfg;
	if (d->cfg.sample_rate <= 0) d->cfg.sample_rate = 8000;
	if (d->cfg.block_ms <= 0) d->cfg.block_ms = 20;
	if (d->cfg.target_freq <= 0) d->cfg.target_freq = 450.0;

	d->cb = cb;
	d->user = user;

	d->block_size = (d->cfg.sample_rate * d->cfg.block_ms) / 1000;
	if (d->block_size < 1) d->block_size = 1;

	/* Goertzel coefficient for the nearest DFT bin to target_freq */
	{
		int k = (int) (0.5 + ((double) d->block_size * d->cfg.target_freq) / (double) d->cfg.sample_rate);
		w = (2.0 * M_PI * (double) k) / (double) d->block_size;
		d->goertzel_coeff = 2.0 * cos(w);
	}

	d->buf = (int16_t *) malloc(sizeof(int16_t) * d->block_size);
	if (!d->buf) {
		free(d);
		return NULL;
	}

	tone_dsp_reset(d);
	return d;
}

void tone_dsp_destroy(tone_dsp_t *d)
{
	if (!d) return;
	free(d->buf);
	free(d);
}

void tone_dsp_reset(tone_dsp_t *d)
{
	if (!d) return;
	d->buf_len = 0;
	d->cur_label = BLK_SILENCE;
	d->run_ms = 0;
	d->last_on_ms = 0;
	d->run_begin_ms = 0;
	d->last_on_begin_ms = 0;
	d->run_reported = 0;
	d->total_ms = 0;
	d->last = TONE_NONE;
}

/* Analyze one full block of block_size samples -> coarse label. */
static block_label_t analyze_block(tone_dsp_t *d, const int16_t *blk)
{
	int n;
	double s_prev = 0.0, s_prev2 = 0.0, s;
	double energy = 0.0;   /* sum of squares */
	double goertzel_power, purity, rms;
	int N = d->block_size;

	for (n = 0; n < N; n++) {
		double x = (double) blk[n];
		energy += x * x;
		s = x + d->goertzel_coeff * s_prev - s_prev2;
		s_prev2 = s_prev;
		s_prev = s;
	}

	rms = sqrt(energy / (double) N);
	if (rms < d->cfg.silence_rms) {
		return BLK_SILENCE;
	}

	/* Goertzel magnitude squared at the target bin. */
	goertzel_power = s_prev * s_prev + s_prev2 * s_prev2
		- d->goertzel_coeff * s_prev * s_prev2;

	/* Normalize to a 0..1 purity: for a pure tone at the exact bin,
	 * goertzel_power ~= (N/2) * energy, so 2*power/(N*energy) ~= 1.0. */
	if (energy <= 0.0) {
		purity = 0.0;
	} else {
		purity = (2.0 * goertzel_power) / ((double) N * energy);
	}

	if (purity >= d->cfg.purity_threshold) {
		return BLK_TONE;
	}
	return BLK_OTHER;
}

static void report(tone_dsp_t *d, tone_type_t t, int begin_ms, int end_ms)
{
	d->last = t;
	if (d->cb) {
		d->cb(d->user, t, begin_ms, end_ms);
	}
}

/* Classify a completed (on_ms tone)+(off_ms silence) cadence cycle. */
static void classify_cycle(tone_dsp_t *d, int on_ms, int off_ms, int begin_ms, int end_ms)
{
	const tone_dsp_config_t *c = &d->cfg;

	if (in_range(on_ms, c->busy_on_min, c->busy_on_max) &&
		in_range(off_ms, c->busy_off_min, c->busy_off_max)) {
		report(d, TONE_BUSY, begin_ms, end_ms);
		return;
	}
	if (in_range(on_ms, c->cong_on_min, c->cong_on_max) &&
		in_range(off_ms, c->cong_off_min, c->cong_off_max)) {
		report(d, TONE_CONGESTION, begin_ms, end_ms);
		return;
	}
	if (in_range(on_ms, c->ring_on_min, c->ring_on_max) &&
		in_range(off_ms, c->ring_off_min, c->ring_off_max)) {
		report(d, TONE_RINGBACK, begin_ms, end_ms);
		return;
	}
	/* sustained tone that doesn't fit a cadence -> raw 450hz */
	if (on_ms >= c->min_tone_ms) {
		report(d, TONE_450HZ, begin_ms, end_ms);
	}
}

/* True once we have locked onto a real cadence; a raw 450hz "tone present"
 * report must not downgrade such a result. */
static int has_cadence_lock(const tone_dsp_t *d)
{
	return d->last == TONE_BUSY || d->last == TONE_CONGESTION || d->last == TONE_RINGBACK;
}

/* Handle a run that just ended (label/run_ms). */
static void close_run(tone_dsp_t *d, block_label_t label, int run_ms, int begin_ms)
{
	if (label == BLK_TONE) {
		/* remember this ON run so the next silence completes a cadence cycle */
		d->last_on_ms = run_ms;
		d->last_on_begin_ms = begin_ms;
	} else if (label == BLK_SILENCE) {
		if (d->last_on_ms > 0) {
			classify_cycle(d, d->last_on_ms, run_ms, d->last_on_begin_ms, d->total_ms);
		}
	}
	/* OTHER runs were already reported in-run */
}

/* Called once per analyzed block with its coarse label. */
static void feed_label(tone_dsp_t *d, block_label_t label)
{
	int blk = d->cfg.block_ms;

	if (label != d->cur_label) {
		close_run(d, d->cur_label, d->run_ms, d->run_begin_ms);
		d->cur_label = label;
		d->run_ms = blk;
		d->run_begin_ms = d->total_ms;
		d->run_reported = 0;
	} else {
		d->run_ms += blk;
	}

	/* Sustained in-run reporting: handles files without transitions and the
	 * trailing run at end-of-stream. */
	if (d->cur_label == BLK_TONE) {
		/* preliminary "tone present" only before a cadence is locked */
		if (!d->run_reported && d->run_ms >= d->cfg.min_tone_ms &&
			(d->last == TONE_NONE || d->last == TONE_SILENCE)) {
			report(d, TONE_450HZ, d->run_begin_ms, d->total_ms);
			d->run_reported = 1;
		}
	} else if (d->cur_label == BLK_OTHER) {
		if (!d->run_reported && d->run_ms >= d->cfg.min_other_ms) {
			report(d, TONE_OTHER, d->run_begin_ms, d->total_ms);
			d->run_reported = 1;
		}
	} else { /* BLK_SILENCE */
		/* early ringback: long gap after a ~1s tone, don't wait full ~4s */
		if (!d->run_reported && !has_cadence_lock(d) && d->last_on_ms > 0 &&
			in_range(d->last_on_ms, d->cfg.ring_on_min, d->cfg.ring_on_max) &&
			d->run_ms >= d->cfg.ring_early_off_ms) {
			report(d, TONE_RINGBACK, d->last_on_begin_ms, d->total_ms);
			d->run_reported = 1;
		}
		/* sustained silence from a silent start */
		else if (!d->run_reported && d->last == TONE_NONE && d->last_on_ms == 0 &&
			d->run_ms >= d->cfg.silence_min_ms) {
			report(d, TONE_SILENCE, d->run_begin_ms, d->total_ms);
			d->run_reported = 1;
		}
	}

	d->total_ms += blk;
}

void tone_dsp_process(tone_dsp_t *d, const int16_t *samples, int nsamples)
{
	int i = 0;
	if (!d || !samples || nsamples <= 0) return;

	while (i < nsamples) {
		int need = d->block_size - d->buf_len;
		int avail = nsamples - i;
		int take = avail < need ? avail : need;

		memcpy(d->buf + d->buf_len, samples + i, sizeof(int16_t) * take);
		d->buf_len += take;
		i += take;

		if (d->buf_len == d->block_size) {
			block_label_t lbl = analyze_block(d, d->buf);
			feed_label(d, lbl);
			d->buf_len = 0;
		}
	}
}

tone_type_t tone_dsp_last(const tone_dsp_t *d)
{
	return d ? d->last : TONE_NONE;
}

const char *tone_type_name(tone_type_t t)
{
	switch (t) {
	case TONE_SILENCE:    return "silence";
	case TONE_450HZ:      return "450hz";
	case TONE_RINGBACK:   return "ringback";
	case TONE_BUSY:       return "busy";
	case TONE_CONGESTION: return "congestion";
	case TONE_OTHER:      return "other";
	case TONE_NONE:
	default:              return "none";
	}
}
