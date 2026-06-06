#include "wavfile.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint32_t rd_u32(const unsigned char *p) {
	return (uint32_t) p[0] | ((uint32_t) p[1] << 8) | ((uint32_t) p[2] << 16) | ((uint32_t) p[3] << 24);
}
static uint16_t rd_u16(const unsigned char *p) {
	return (uint16_t) p[0] | ((uint16_t) p[1] << 8);
}

int wav_read_mono16(const char *path, int16_t **out_samples, int *out_nsamples, int *out_rate)
{
	FILE *f = fopen(path, "rb");
	unsigned char hdr[12];
	int rate = 0, channels = 0, bits = 0;
	int16_t *data = NULL;
	int ndata = 0;

	if (!f) return 1;

	if (fread(hdr, 1, 12, f) != 12 || memcmp(hdr, "RIFF", 4) != 0 || memcmp(hdr + 8, "WAVE", 4) != 0) {
		fclose(f);
		return 2;
	}

	for (;;) {
		unsigned char ch[8];
		uint32_t csize;
		if (fread(ch, 1, 8, f) != 8) break;
		csize = rd_u32(ch + 4);

		if (memcmp(ch, "fmt ", 4) == 0) {
			unsigned char fmt[16];
			uint32_t toread = csize < 16 ? csize : 16;
			if (fread(fmt, 1, toread, f) != toread) { fclose(f); return 3; }
			channels = rd_u16(fmt + 2);
			rate = (int) rd_u32(fmt + 4);
			bits = rd_u16(fmt + 14);
			if (csize > toread) fseek(f, (long) (csize - toread), SEEK_CUR);
		} else if (memcmp(ch, "data", 4) == 0) {
			int nbytes = (int) csize;
			unsigned char *raw = (unsigned char *) malloc(nbytes);
			if (!raw) { fclose(f); return 4; }
			if (fread(raw, 1, nbytes, f) != (size_t) nbytes) { free(raw); fclose(f); return 5; }
			if (bits != 16) { free(raw); fclose(f); return 6; }
			{
				int total = nbytes / 2;            /* total int16 across channels */
				int frames = channels > 0 ? total / channels : total;
				int i;
				data = (int16_t *) malloc(sizeof(int16_t) * frames);
				if (!data) { free(raw); fclose(f); return 7; }
				for (i = 0; i < frames; i++) {
					/* take channel 0 only */
					data[i] = (int16_t) rd_u16(raw + (size_t) i * channels * 2);
				}
				ndata = frames;
			}
			free(raw);
			break;
		} else {
			fseek(f, (long) csize, SEEK_CUR);
		}
	}

	fclose(f);
	if (!data) return 8;

	*out_samples = data;
	*out_nsamples = ndata;
	*out_rate = rate;
	return 0;
}

static void wr_u32(FILE *f, uint32_t v) {
	unsigned char b[4] = { (unsigned char) v, (unsigned char) (v >> 8), (unsigned char) (v >> 16), (unsigned char) (v >> 24) };
	fwrite(b, 1, 4, f);
}
static void wr_u16(FILE *f, uint16_t v) {
	unsigned char b[2] = { (unsigned char) v, (unsigned char) (v >> 8) };
	fwrite(b, 1, 2, f);
}

int wav_write_mono16(const char *path, const int16_t *samples, int nsamples, int rate)
{
	FILE *f = fopen(path, "wb");
	uint32_t databytes = (uint32_t) nsamples * 2;
	if (!f) return 1;

	fwrite("RIFF", 1, 4, f);
	wr_u32(f, 36 + databytes);
	fwrite("WAVE", 1, 4, f);

	fwrite("fmt ", 1, 4, f);
	wr_u32(f, 16);
	wr_u16(f, 1);                       /* PCM */
	wr_u16(f, 1);                       /* mono */
	wr_u32(f, (uint32_t) rate);
	wr_u32(f, (uint32_t) (rate * 2));   /* byte rate */
	wr_u16(f, 2);                       /* block align */
	wr_u16(f, 16);                      /* bits */

	fwrite("data", 1, 4, f);
	wr_u32(f, databytes);
	fwrite(samples, 2, (size_t) nsamples, f);

	fclose(f);
	return 0;
}
