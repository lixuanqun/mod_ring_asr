/*
 * tone_dsp.h -- Call-progress signal tone detector (China 450Hz plan).
 *
 * FreeSWITCH-independent DSP core. It consumes 16-bit mono PCM and
 * classifies call-progress signal tones using a Goertzel single-frequency
 * detector plus a cadence (on/off rhythm) state machine.
 *
 * Phase 1 scope (China 450Hz tone plan):
 *   - ringback   (回铃音):   450Hz, on ~1000ms / off ~4000ms
 *   - busy       (忙音):     450Hz, on ~350ms  / off ~350ms
 *   - congestion (拥塞/快忙): 450Hz, on ~700ms  / off ~700ms
 *   - 450hz      (嘟音):     sustained 450Hz that does not (yet) match a cadence
 *   - silence    (静音)
 *   - other      (非纯音, 可能是彩铃/语音, 留给阶段2的识别服务处理)
 *
 * The core is deliberately decoupled from FreeSWITCH so it can be unit
 * tested offline by feeding WAV samples.
 */
#ifndef TONE_DSP_H
#define TONE_DSP_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
	TONE_NONE = 0,    /* nothing decided yet */
	TONE_SILENCE,     /* energy below the silence floor */
	TONE_450HZ,       /* sustained 450Hz present, cadence not yet matched */
	TONE_RINGBACK,    /* 回铃音 */
	TONE_BUSY,        /* 忙音 */
	TONE_CONGESTION,  /* 拥塞音 / 快忙 */
	TONE_OTHER        /* energy present but not 450Hz dominant (voice/colorring) */
} tone_type_t;

typedef struct {
	int    sample_rate;       /* default 8000 */
	double target_freq;       /* default 450.0 */
	int    block_ms;          /* analysis block size in ms, default 20 */

	double purity_threshold;  /* 0..1, fraction of energy at target freq to call it a tone, default 0.40 */
	double silence_rms;       /* RMS below this (out of 32768) is silence, default 200.0 */

	/* cadence rules, in milliseconds: on/off durations with tolerance */
	int busy_on_min, busy_on_max, busy_off_min, busy_off_max;
	int cong_on_min, cong_on_max, cong_off_min, cong_off_max;
	int ring_on_min, ring_on_max, ring_off_min, ring_off_max;

	/* if a tone run matched ringback's ON range and silence already
	 * lasted this long, declare ringback early instead of waiting the
	 * full ~4s OFF period (speeds up detection). default 2000ms */
	int ring_early_off_ms;

	/* a tone run must last at least this long to be reported as 450hz, default 150ms */
	int min_tone_ms;
	/* an OTHER (non-tone energy) run must last at least this long to report, default 400ms */
	int min_other_ms;
	/* sustained silence (from a silent start) reported after this long, default 1000ms */
	int silence_min_ms;
} tone_dsp_config_t;

/* Fired whenever the detector reaches a new classification. begin_ms/end_ms
 * are stream-relative timestamps (ms since reset) bounding the evidence. */
typedef void (*tone_dsp_cb)(void *user, tone_type_t type, int begin_ms, int end_ms);

typedef struct tone_dsp_s tone_dsp_t;

/* Fill cfg with China-450Hz defaults (matches mod_da2-style rule ranges). */
void tone_dsp_config_default(tone_dsp_config_t *cfg);

tone_dsp_t *tone_dsp_create(const tone_dsp_config_t *cfg, tone_dsp_cb cb, void *user);
void tone_dsp_destroy(tone_dsp_t *d);
void tone_dsp_reset(tone_dsp_t *d);

/* Feed mono int16 PCM samples. May fire the callback zero or more times. */
void tone_dsp_process(tone_dsp_t *d, const int16_t *samples, int nsamples);

/* Last classification reached so far (sticky). */
tone_type_t tone_dsp_last(const tone_dsp_t *d);

const char *tone_type_name(tone_type_t t);

#ifdef __cplusplus
}
#endif

#endif /* TONE_DSP_H */
