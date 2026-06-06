# Standalone build for mod_tonedetect against an installed FreeSWITCH.
#
#   make                 # build mod_tonedetect.so
#   sudo make install    # install .so and tonedetect.conf.xml
#
# Override paths if your FreeSWITCH lives elsewhere:
#   make FS_INCLUDE=/usr/local/freeswitch/include FS_MODDIR=/usr/local/freeswitch/mod

CC        ?= gcc
FS_INCLUDE ?= /usr/include/freeswitch
FS_MODDIR  ?= /usr/lib/freeswitch/mod
FS_CONFDIR ?= /etc/freeswitch/autoload_configs

CFLAGS  ?= -O2 -fPIC -Wall -Wextra
CFLAGS  += -I$(FS_INCLUDE) -I../src
LDFLAGS += -shared

SRC := mod_tonedetect.c ../src/tone_dsp.c ../src/ws_client.c
TARGET := mod_tonedetect.so

.PHONY: all clean install

all: $(TARGET)

$(TARGET): $(SRC) ../src/tone_dsp.h ../src/ws_client.h
	$(CC) $(CFLAGS) $(SRC) -o $(TARGET) $(LDFLAGS) -lm -lwebsockets -lpthread

install: $(TARGET)
	install -m 0755 $(TARGET) $(FS_MODDIR)/$(TARGET)
	install -m 0644 tonedetect.conf.xml $(FS_CONFDIR)/tonedetect.conf.xml

clean:
	rm -f $(TARGET)
