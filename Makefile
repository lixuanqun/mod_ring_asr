# Offline build & test for the tone-detection DSP core.
# (The FreeSWITCH module itself is built separately, see module/.)

CC      ?= gcc
CFLAGS  ?= -O2 -Wall -Wextra -std=c99
LDLIBS  := -lm
BUILD   := build
WAVDIR  := $(BUILD)/test_wavs

.PHONY: all test clean tones

all: $(BUILD)/test_dsp $(BUILD)/gen_tones

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/tone_dsp.o: src/tone_dsp.c src/tone_dsp.h | $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/wavfile.o: test/wavfile.c test/wavfile.h | $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/test_dsp: test/test_dsp.c $(BUILD)/tone_dsp.o $(BUILD)/wavfile.o | $(BUILD)
	$(CC) $(CFLAGS) $^ -o $@ $(LDLIBS)

$(BUILD)/gen_tones: test/gen_tones.c $(BUILD)/wavfile.o | $(BUILD)
	$(CC) $(CFLAGS) $^ -o $@ $(LDLIBS)

tones: $(BUILD)/gen_tones
	$(BUILD)/gen_tones $(WAVDIR)

# Generate synthetic tones and assert each classifies correctly.
test: all tones
	@echo "=================== DSP detection tests ==================="
	@rc=0; \
	$(BUILD)/test_dsp $(WAVDIR)/silence.wav    silence    || rc=1; \
	$(BUILD)/test_dsp $(WAVDIR)/busy.wav       busy       || rc=1; \
	$(BUILD)/test_dsp $(WAVDIR)/congestion.wav congestion || rc=1; \
	$(BUILD)/test_dsp $(WAVDIR)/ringback.wav   ringback   || rc=1; \
	$(BUILD)/test_dsp $(WAVDIR)/other.wav      other      || rc=1; \
	$(BUILD)/test_dsp $(WAVDIR)/ringback_then_busy.wav busy || rc=1; \
	echo "==========================================================="; \
	if [ $$rc -eq 0 ]; then echo "ALL TESTS PASSED"; else echo "SOME TESTS FAILED"; fi; \
	exit $$rc

clean:
	rm -rf $(BUILD)
