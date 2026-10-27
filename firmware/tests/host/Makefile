# Host unit tests for the portable firmware modules (no Zephyr):
#   make -C firmware/tests/host run        (also run in CI, with sanitizers)
SRC := ../../src
CFLAGS ?= -std=c99 -Wall -Wextra -Werror -O1 -g -I$(SRC)
SAN ?= -fsanitize=address,undefined -fno-sanitize-recover=all
OUT := out
MODS := $(SRC)/raw_pack.c $(SRC)/ringbuf.c $(SRC)/punch_detect.c $(SRC)/evlog.c $(SRC)/btrk_util.c

$(OUT)/test_host: test_host.c $(MODS) $(wildcard $(SRC)/*.h)
	mkdir -p $(OUT)
	$(CC) $(CFLAGS) $(SAN) -o $@ test_host.c $(MODS) -lm

$(OUT)/pd_cli: pd_cli.c $(SRC)/punch_detect.c $(wildcard $(SRC)/*.h)
	mkdir -p $(OUT)
	$(CC) $(CFLAGS) -o $@ pd_cli.c $(SRC)/punch_detect.c -lm

run: $(OUT)/test_host $(OUT)/pd_cli
	./$(OUT)/test_host

clean:
	rm -rf $(OUT)
.PHONY: run clean
