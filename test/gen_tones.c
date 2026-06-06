/*
 * gen_tones.c -- generate synthetic China-450Hz call-progress WAVs for tests.
 *
 * Usage: gen_tones [out_dir]   (default: test_wavs)
 *
 * Produces:
 *   ringback.wav    450Hz on 1000 / off 4000
 *   busy.wav        450Hz on 350  / off 350
 *   congestion.wav  450Hz on 700  / off 700
 *   silence.wav     near-silent
 *   other.wav       multi-tone "music" (colorring stand-in, not 450-dominant)
 *   ringback_then_busy.wav  ringback cycles followed by busy (state scenario)
 */
#include "wavfile.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define RATE 8000
#define AMP  8000.0
#define NOISE 60.0   /* small background noise amplitude */

static double frand(void) { return (double) rand() / (double) RAND_MAX; }

/* append `ms` of a sine at `freq` (or silence if freq<=0) to buf at *pos */
static void append_seg(int16_t *buf, int *pos, int cap, double freq, int ms, double amp)
{
	int n = (RATE * ms) / 1000;
	int i;
	for (i = 0; i < n && *pos < cap; i++, (*pos)++) {
		double v = (NOISE * (frand() * 2.0 - 1.0));
		if (freq > 0.0) {
			v += amp * sin(2.0 * M_PI * freq * (double) (*pos) / (double) RATE);
		}
		if (v > 32767.0) v = 32767.0;
		if (v < -32768.0) v = -32768.0;
		buf[*pos] = (int16_t) v;
	}
}

/* append `ms` of a 3-tone "music" mix */
static void append_music(int16_t *buf, int *pos, int cap, int ms)
{
	int n = (RATE * ms) / 1000;
	int i;
	for (i = 0; i < n && *pos < cap; i++, (*pos)++) {
		double t = (double) (*pos) / (double) RATE;
		double v = 3000.0 * sin(2.0 * M_PI * 330.0 * t)
		         + 2500.0 * sin(2.0 * M_PI * 660.0 * t)
		         + 2000.0 * sin(2.0 * M_PI * 990.0 * t)
		         + 1500.0 * (frand() * 2.0 - 1.0);
		if (v > 32767.0) v = 32767.0;
		if (v < -32768.0) v = -32768.0;
		buf[*pos] = (int16_t) v;
	}
}

static int gen_cadence(const char *dir, const char *name, double freq,
                       int on_ms, int off_ms, int cycles)
{
	int cap = (RATE * (on_ms + off_ms) / 1000) * cycles + RATE;
	int16_t *buf = (int16_t *) calloc(cap, sizeof(int16_t));
	int pos = 0, c;
	char path[512];

	if (!buf) return 1;
	for (c = 0; c < cycles; c++) {
		append_seg(buf, &pos, cap, freq, on_ms, AMP);
		append_seg(buf, &pos, cap, 0.0, off_ms, AMP);
	}
	snprintf(path, sizeof(path), "%s/%s", dir, name);
	wav_write_mono16(path, buf, pos, RATE);
	free(buf);
	printf("  wrote %s (%d ms)\n", path, (pos * 1000) / RATE);
	return 0;
}

int main(int argc, char **argv)
{
	const char *dir = argc > 1 ? argv[1] : "test_wavs";
	char cmd[600];
	char path[512];

	snprintf(cmd, sizeof(cmd), "mkdir -p '%s'", dir);
	if (system(cmd) != 0) { fprintf(stderr, "mkdir failed\n"); return 1; }

	srand(12345);
	printf("generating synthetic tones into %s/\n", dir);

	gen_cadence(dir, "ringback.wav",   450.0, 1000, 4000, 2);
	gen_cadence(dir, "busy.wav",       450.0,  350,  350, 8);
	gen_cadence(dir, "congestion.wav", 450.0,  700,  700, 5);

	/* silence */
	{
		int cap = RATE * 3;
		int16_t *buf = (int16_t *) calloc(cap, sizeof(int16_t));
		int pos = 0;
		if (buf) {
			append_seg(buf, &pos, cap, 0.0, 3000, AMP);
			snprintf(path, sizeof(path), "%s/silence.wav", dir);
			wav_write_mono16(path, buf, pos, RATE);
			free(buf);
			printf("  wrote %s (%d ms)\n", path, (pos * 1000) / RATE);
		}
	}

	/* other / colorring stand-in: continuous multi-tone music */
	{
		int cap = RATE * 4;
		int16_t *buf = (int16_t *) calloc(cap, sizeof(int16_t));
		int pos = 0;
		if (buf) {
			append_music(buf, &pos, cap, 4000);
			snprintf(path, sizeof(path), "%s/other.wav", dir);
			wav_write_mono16(path, buf, pos, RATE);
			free(buf);
			printf("  wrote %s (%d ms)\n", path, (pos * 1000) / RATE);
		}
	}

	/* scenario: 1 ringback cycle then busy (caller picks up busy) */
	{
		int cap = RATE * 20;
		int16_t *buf = (int16_t *) calloc(cap, sizeof(int16_t));
		int pos = 0, c;
		if (buf) {
			append_seg(buf, &pos, cap, 450.0, 1000, AMP);
			append_seg(buf, &pos, cap, 0.0,   4000, AMP);
			for (c = 0; c < 6; c++) {
				append_seg(buf, &pos, cap, 450.0, 350, AMP);
				append_seg(buf, &pos, cap, 0.0,   350, AMP);
			}
			snprintf(path, sizeof(path), "%s/ringback_then_busy.wav", dir);
			wav_write_mono16(path, buf, pos, RATE);
			free(buf);
			printf("  wrote %s (%d ms)\n", path, (pos * 1000) / RATE);
		}
	}

	printf("done.\n");
	return 0;
}
