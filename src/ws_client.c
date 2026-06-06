/*
 * ws_client.c -- libwebsockets-based client (see ws_client.h).
 */
#include "ws_client.h"

#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <pthread.h>

#include <libwebsockets.h>

/* one queued outbound message */
typedef struct ws_msg_s {
	unsigned char *payload;   /* LWS_PRE bytes of headroom + data */
	size_t len;               /* data length (excluding LWS_PRE) */
	int binary;               /* 1 = binary frame, 0 = text */
	struct ws_msg_s *next;
} ws_msg_t;

struct ws_client_s {
	char host[256];
	char path[256];
	int port;

	ws_client_result_cb cb;
	void *user;

	struct lws_context *context;
	struct lws *wsi;

	pthread_t thread;
	pthread_mutex_t lock;
	int running;
	int connected;

	ws_msg_t *q_head, *q_tail;

	/* reassembly buffer for incoming (possibly fragmented) text frames */
	unsigned char *rx_buf;
	size_t rx_len, rx_cap;
};

static int parse_url(ws_client_t *c, const char *url)
{
	const char *p = url;
	const char *hoststart, *colon, *slash;
	size_t hostlen;

	if (!strncmp(p, "ws://", 5)) p += 5;
	else if (!strncmp(p, "WS://", 5)) p += 5;

	hoststart = p;
	slash = strchr(p, '/');
	colon = strchr(p, ':');

	c->port = 80;
	if (colon && (!slash || colon < slash)) {
		hostlen = (size_t) (colon - hoststart);
		c->port = atoi(colon + 1);
	} else if (slash) {
		hostlen = (size_t) (slash - hoststart);
	} else {
		hostlen = strlen(hoststart);
	}
	if (hostlen >= sizeof(c->host)) hostlen = sizeof(c->host) - 1;
	memcpy(c->host, hoststart, hostlen);
	c->host[hostlen] = '\0';

	if (slash) {
		snprintf(c->path, sizeof(c->path), "%s", slash);
	} else {
		snprintf(c->path, sizeof(c->path), "/");
	}
	return c->host[0] ? 0 : -1;
}

static int enqueue(ws_client_t *c, const void *data, size_t len, int binary)
{
	ws_msg_t *m = (ws_msg_t *) calloc(1, sizeof(*m));
	if (!m) return -1;
	m->payload = (unsigned char *) malloc(LWS_PRE + len);
	if (!m->payload) { free(m); return -1; }
	memcpy(m->payload + LWS_PRE, data, len);
	m->len = len;
	m->binary = binary;

	pthread_mutex_lock(&c->lock);
	if (c->q_tail) c->q_tail->next = m; else c->q_head = m;
	c->q_tail = m;
	pthread_mutex_unlock(&c->lock);

	if (c->context) lws_cancel_service(c->context);
	return 0;
}

static ws_msg_t *dequeue(ws_client_t *c)
{
	ws_msg_t *m;
	pthread_mutex_lock(&c->lock);
	m = c->q_head;
	if (m) {
		c->q_head = m->next;
		if (!c->q_head) c->q_tail = NULL;
	}
	pthread_mutex_unlock(&c->lock);
	return m;
}

static int has_queued(ws_client_t *c)
{
	int r;
	pthread_mutex_lock(&c->lock);
	r = c->q_head != NULL;
	pthread_mutex_unlock(&c->lock);
	return r;
}

static int proto_cb(struct lws *wsi, enum lws_callback_reasons reason,
                    void *user, void *in, size_t len)
{
	struct lws_context *ctx = lws_get_context(wsi);
	ws_client_t *c = (ws_client_t *) lws_context_user(ctx);
	(void) user;

	switch (reason) {
	case LWS_CALLBACK_CLIENT_ESTABLISHED:
		c->connected = 1;
		lws_callback_on_writable(wsi);
		break;

	case LWS_CALLBACK_CLIENT_CONNECTION_ERROR:
		c->connected = 0;
		c->wsi = NULL;
		break;

	case LWS_CALLBACK_CLIENT_RECEIVE:
	{
		size_t remaining = lws_remaining_packet_payload(wsi);
		if (c->rx_len + len + 1 > c->rx_cap) {
			size_t ncap = (c->rx_len + len + 1) * 2;
			unsigned char *nb = (unsigned char *) realloc(c->rx_buf, ncap);
			if (!nb) break;
			c->rx_buf = nb;
			c->rx_cap = ncap;
		}
		memcpy(c->rx_buf + c->rx_len, in, len);
		c->rx_len += len;

		if (remaining == 0 && lws_is_final_fragment(wsi)) {
			c->rx_buf[c->rx_len] = '\0';
			if (c->cb) c->cb(c->user, (const char *) c->rx_buf, c->rx_len);
			c->rx_len = 0;
		}
		break;
	}

	case LWS_CALLBACK_EVENT_WAIT_CANCELLED:
		/* woken by enqueue(): ask to write if we have a connection */
		if (c->wsi && c->connected) lws_callback_on_writable(c->wsi);
		break;

	case LWS_CALLBACK_CLIENT_WRITEABLE:
	{
		ws_msg_t *m = dequeue(c);
		if (m) {
			enum lws_write_protocol wp = m->binary ? LWS_WRITE_BINARY : LWS_WRITE_TEXT;
			int n = lws_write(wsi, m->payload + LWS_PRE, m->len, wp);
			free(m->payload);
			free(m);
			if (n < 0) return -1;
			if (has_queued(c)) lws_callback_on_writable(wsi);
		}
		break;
	}

	case LWS_CALLBACK_CLIENT_CLOSED:
		c->connected = 0;
		c->wsi = NULL;
		break;

	default:
		break;
	}
	return 0;
}

static struct lws_protocols protocols[] = {
	{ "tonedetect", proto_cb, 0, 65536, 0, NULL, 0 },
	LWS_PROTOCOL_LIST_TERM
};

static void *service_thread(void *arg)
{
	ws_client_t *c = (ws_client_t *) arg;
	while (c->running) {
		lws_service(c->context, 50);
	}
	return NULL;
}

ws_client_t *ws_client_create(const char *url, ws_client_result_cb cb, void *user)
{
	ws_client_t *c = (ws_client_t *) calloc(1, sizeof(*c));
	if (!c) return NULL;
	c->cb = cb;
	c->user = user;
	pthread_mutex_init(&c->lock, NULL);
	if (parse_url(c, url) != 0) {
		free(c);
		return NULL;
	}
	return c;
}

int ws_client_start(ws_client_t *c)
{
	struct lws_context_creation_info info;
	struct lws_client_connect_info ccinfo;

	if (!c) return -1;

	memset(&info, 0, sizeof(info));
	info.port = CONTEXT_PORT_NO_LISTEN;
	info.protocols = protocols;
	info.gid = -1;
	info.uid = -1;
	info.user = c;
	info.options = 0;

	c->context = lws_create_context(&info);
	if (!c->context) return -1;

	memset(&ccinfo, 0, sizeof(ccinfo));
	ccinfo.context = c->context;
	ccinfo.address = c->host;
	ccinfo.port = c->port;
	ccinfo.path = c->path;
	ccinfo.host = c->host;
	ccinfo.origin = c->host;
	ccinfo.protocol = protocols[0].name;
	ccinfo.pwsi = &c->wsi;

	if (!lws_client_connect_via_info(&ccinfo)) {
		lws_context_destroy(c->context);
		c->context = NULL;
		return -1;
	}

	c->running = 1;
	if (pthread_create(&c->thread, NULL, service_thread, c) != 0) {
		c->running = 0;
		lws_context_destroy(c->context);
		c->context = NULL;
		return -1;
	}
	return 0;
}

int ws_client_send_text(ws_client_t *c, const char *json)
{
	if (!c || !json) return -1;
	return enqueue(c, json, strlen(json), 0);
}

int ws_client_send_audio(ws_client_t *c, const int16_t *pcm, int nsamples)
{
	if (!c || !pcm || nsamples <= 0) return -1;
	return enqueue(c, pcm, (size_t) nsamples * sizeof(int16_t), 1);
}

int ws_client_is_connected(ws_client_t *c)
{
	return c ? c->connected : 0;
}

void ws_client_stop(ws_client_t *c)
{
	if (!c) return;
	if (c->running) {
		c->running = 0;
		if (c->context) lws_cancel_service(c->context);
		pthread_join(c->thread, NULL);
	}
	if (c->context) {
		lws_context_destroy(c->context);
		c->context = NULL;
	}
}

void ws_client_destroy(ws_client_t *c)
{
	ws_msg_t *m;
	if (!c) return;
	ws_client_stop(c);
	while ((m = dequeue(c))) {
		free(m->payload);
		free(m);
	}
	free(c->rx_buf);
	pthread_mutex_destroy(&c->lock);
	free(c);
}
