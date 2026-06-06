/*
 * test_dsp.c -- offline harness: run the tone detector over a WAV file and
 * print the detection timeline plus the final classification.
 *
 * Usage:
 *   test_dsp <file.wav> [expected_tone]
 *
 * If expected_tone is given (e.g. "ringback"), exit code is 0 only when the
 * detector's final sticky classification matches; otherwise 1. This lets the
 * test runner assert correctness.
 */
#include "../src/tone_dsp.h"
#include "wavfile.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void on_tone(void *user, tone_type_t type, int begin_ms, int end_ms)
{
	(void) user;
	printf("    [%6d - %6d ms] -> %s\n", begin_ms, end_ms, tone_type_name(type));
}

int main(int argc, char **argv)
{
	int16_t *samples = NULL;
	int nsamples = 0, rate = 0;
	const char *path, *expected = NULL;
	tone_dsp_config_t cfg;
	tone_dsp_t *d;
	tone_type_t final;
	int chunk = 160; /* simulate 20ms @ 8k frames like FreeSWITCH media bug */
	int i;

	if (argc < 2) {
		fprintf(stderr, "usage: %s <file.wav> [expected_tone]\n", argv[0]);
		return 2;
	}
	path = argv[1];
	if (argc >= 3) expected = argv[2];

	if (wav_read_mono16(path, &samples, &nsamples, &rate) != 0) {
		fprintf(stderr, "failed to read wav: %s\n", path);
		return 2;
	}

	tone_dsp_config_default(&cfg);
	cfg.sample_rate = rate;
	chunk = (rate * 20) / 1000;
	if (chunk < 1) chunk = 160;

	d = tone_dsp_create(&cfg, on_tone, NULL);
	if (!d) {
		fprintf(stderr, "failed to create detector\n");
		free(samples);
		return 2;
	}

	printf("== %s (%d samples @ %dHz, %.2fs) ==\n",
		path, nsamples, rate, (double) nsamples / (double) rate);

	for (i = 0; i < nsamples; i += chunk) {
		int n = nsamples - i;
		if (n > chunk) n = chunk;
		tone_dsp_process(d, samples + i, n);
	}

	final = tone_dsp_last(d);
	printf("  FINAL: %s\n", tone_type_name(final));

	tone_dsp_destroy(d);
	free(samples);

	if (expected) {
		if (strcmp(tone_type_name(final), expected) == 0) {
			printf("  PASS (expected %s)\n", expected);
			return 0;
		}
		printf("  FAIL (expected %s, got %s)\n", expected, tone_type_name(final));
		return 1;
	}
	return 0;
}
