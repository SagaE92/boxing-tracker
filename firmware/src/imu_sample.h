/* imu_sample.h - one timestamped raw 6-axis sample (portable C) */
#ifndef IMU_SAMPLE_H_
#define IMU_SAMPLE_H_
#include <stdint.h>

struct imu_sample {
	uint32_t t_us;   /* device time (us, wraps ~71.6 min) */
	int16_t a[3];    /* accel raw, chip axes, 0.488 mg/LSB @ +-16 g */
	int16_t g[3];    /* gyro raw, chip axes, 70 mdps/LSB @ +-2000 dps */
};

#endif
