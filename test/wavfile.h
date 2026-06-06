/*
 * wavfile.h -- tiny mono 16-bit PCM WAV reader/writer for offline tests.
 */
#ifndef WAVFILE_H
#define WAVFILE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Read a mono 16-bit PCM WAV. Returns malloc'd samples (caller frees) via
 * *out_samples, count via *out_nsamples and rate via *out_rate.
 * Returns 0 on success, non-zero on error. */
int wav_read_mono16(const char *path, int16_t **out_samples, int *out_nsamples, int *out_rate);

/* Write a mono 16-bit PCM WAV. Returns 0 on success. */
int wav_write_mono16(const char *path, const int16_t *samples, int nsamples, int rate);

#ifdef __cplusplus
}
#endif

#endif /* WAVFILE_H */
