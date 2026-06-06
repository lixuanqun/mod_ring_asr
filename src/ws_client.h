/*
 * ws_client.h -- minimal libwebsockets client for streaming L16 audio to the
 * tonedetect recognition service and receiving JSON results.
 *
 * FreeSWITCH-independent so it can be reused by mod_tonedetect and unit-tested
 * by a standalone harness. Runs its own service thread; audio is enqueued from
 * any thread (e.g. a media-bug callback) and written by the service thread.
 */
#ifndef WS_CLIENT_H
#define WS_CLIENT_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ws_client_s ws_client_t;

/* Invoked (on the service thread) for each text frame received from the
 * server, e.g. a RESULT JSON. `json` is NUL-terminated. */
typedef void (*ws_client_result_cb)(void *user, const char *json, size_t len);

/* url example: "ws://127.0.0.1:9977/" (only ws:// is supported here). */
ws_client_t *ws_client_create(const char *url, ws_client_result_cb cb, void *user);

/* Connect and start the service thread. Returns 0 on success. */
int ws_client_start(ws_client_t *c);

/* Enqueue a text frame (e.g. START/STOP JSON). Returns 0 on success. */
int ws_client_send_text(ws_client_t *c, const char *json);

/* Enqueue a binary frame of int16 PCM samples. Returns 0 on success. */
int ws_client_send_audio(ws_client_t *c, const int16_t *pcm, int nsamples);

/* 1 if the websocket is established. */
int ws_client_is_connected(ws_client_t *c);

/* Stop the service thread and close the connection. */
void ws_client_stop(ws_client_t *c);
void ws_client_destroy(ws_client_t *c);

#ifdef __cplusplus
}
#endif

#endif /* WS_CLIENT_H */
