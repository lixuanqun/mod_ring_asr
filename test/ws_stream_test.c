/*
 * ws_stream_test.c -- stream a WAV to the tonedetect recognition service over
 * WebSocket (using the real C ws_client) and print RESULT JSON.
 *
 * Usage: ws_stream_test <ws-url> <file.wav> [expect_substr]
 *   exit 0 if a result containing expect_substr was received (or no expect given)
 */
#define _DEFAULT_SOURCE
#include "../src/ws_client.h"
#include "wavfile.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int g_hits = 0;
static char g_expect[256] = "";

static void on_result(void *user, const char *json, size_t len)
{
	(void) user; (void) len;
	printf("  RESULT: %s\n", json);
	if (g_expect[0] && strstr(json, g_expect)) g_hits++;
}

int main(int argc, char **argv)
{
	const char *url, *path;
	int16_t *samples = NULL;
	int nsamples = 0, rate = 0;
	ws_client_t *c;
	int i, chunk, waited;
	char start_json[512];

	if (argc < 3) {
		fprintf(stderr, "usage: %s <ws-url> <file.wav> [expect_substr]\n", argv[0]);
		return 2;
	}
	url = argv[1];
	path = argv[2];
	if (argc >= 4) snprintf(g_expect, sizeof(g_expect), "%s", argv[3]);

	if (wav_read_mono16(path, &samples, &nsamples, &rate) != 0) {
		fprintf(stderr, "failed to read wav: %s\n", path);
		return 2;
	}

	c = ws_client_create(url, on_result, NULL);
	if (!c || ws_client_start(c) != 0) {
		fprintf(stderr, "failed to start ws client\n");
		return 2;
	}

	/* wait for connection */
	for (waited = 0; waited < 100 && !ws_client_is_connected(c); waited++) {
		usleep(50 * 1000);
	}
	if (!ws_client_is_connected(c)) {
		fprintf(stderr, "could not connect to %s\n", url);
		ws_client_destroy(c);
		return 2;
	}
	printf("connected to %s, streaming %s (%d samples @ %dHz)\n", url, path, nsamples, rate);

	snprintf(start_json, sizeof(start_json),
		"{\"type\":\"start\",\"version\":1,\"uuid\":\"ctest\",\"codec\":\"L16\",\"samplerate\":%d}", rate);
	ws_client_send_text(c, start_json);
	usleep(100 * 1000);

	chunk = (rate * 20) / 1000; /* 20ms frames */
	for (i = 0; i < nsamples; i += chunk) {
		int n = nsamples - i;
		if (n > chunk) n = chunk;
		ws_client_send_audio(c, samples + i, n);
		usleep(5 * 1000); /* pace a bit so frames flush */
	}

	ws_client_send_text(c, "{\"type\":\"stop\"}");

	/* allow results to arrive */
	for (waited = 0; waited < 60; waited++) usleep(50 * 1000);

	ws_client_destroy(c);
	free(samples);

	if (g_expect[0]) {
		if (g_hits > 0) {
			printf("  PASS (got result containing \"%s\")\n", g_expect);
			return 0;
		}
		printf("  FAIL (no result containing \"%s\")\n", g_expect);
		return 1;
	}
	return 0;
}
