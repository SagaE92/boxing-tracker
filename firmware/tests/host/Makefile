SRC := ../../src
CFLAGS ?= -std=c99 -Wall -Wextra -Werror -O1 -I$(SRC)
OUT := out

$(OUT)/test_host: test_host.c $(SRC)/raw_pack.c $(SRC)/ringbuf.c $(SRC)/punch_detect.c $(wildcard $(SRC)/*.h)
	mkdir -p $(OUT)
	$(CC) $(CFLAGS) -o $@ test_host.c $(SRC)/raw_pack.c $(SRC)/ringbuf.c $(SRC)/punch_detect.c -lm

run: $(OUT)/test_host
	./$(OUT)/test_host

clean:
	rm -rf $(OUT)
.PHONY: run clean
