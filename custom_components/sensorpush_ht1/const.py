"""Constants for the SensorPush HT1 integration."""

DOMAIN = "sensorpush_ht1"

# BLE identity
SENSORPUSH_SERVICE_UUID = "ef090000-11d6-42ba-93b8-9dd7ec090aa9"
HT1_LOCAL_NAME = "s"

# GATT characteristic UUIDs (determined via protocol analysis)
CHAR_DEVICE_ID       = "ef090001-11d6-42ba-93b8-9dd7ec090aa9"  # uint24 LE, 3 bytes
CHAR_TX_POWER        = "ef090003-11d6-42ba-93b8-9dd7ec090aa9"  # int8, dBm
CHAR_MEAS_INTERVAL   = "ef090004-11d6-42ba-93b8-9dd7ec090aa9"  # uint16 LE, seconds (default 60)
CHAR_ADV_INTERVAL    = "ef090005-11d6-42ba-93b8-9dd7ec090aa9"  # uint16 LE, 0.625ms slots
CHAR_ALARM_LOW       = "ef090006-11d6-42ba-93b8-9dd7ec090aa9"  # 4 bytes [temp_raw, hum_raw]
CHAR_BATTERY_VOLTAGE = "ef090007-11d6-42ba-93b8-9dd7ec090aa9"  # uint16 ADC_raw + uint16 die_temp
CHAR_LAST_SEEN       = "ef090008-11d6-42ba-93b8-9dd7ec090aa9"  # uint32 LE unix timestamp
CHAR_HISTORY_CMD     = "ef090009-11d6-42ba-93b8-9dd7ec090aa9"  # write 0x01000000 to trigger
CHAR_HISTORY_DATA    = "ef09000a-11d6-42ba-93b8-9dd7ec090aa9"  # 20-byte notify, 4 records/msg
CHAR_ALARM_HUM       = "ef09000b-11d6-42ba-93b8-9dd7ec090aa9"  # uint16 LE pair [low%, high%]

# Battery voltage formula: nRF52 SAADC, gain=1/6, ref=0.6V, 10-bit
# ADC formula: voltage = (raw & 0x7FFF) * 3.6 / 1024  (3.6V = ADC full-scale)
# CR2 lithium cell characteristics (HT1 uses CR2):
#   Fresh: ~3.1V (may read slightly above nominal off-shelf)
#   Dead:  ~2.1V
BATTERY_ADC_FULL_SCALE = 3.6  # nRF52 SAADC full-scale: gain=1/6, Vref=0.6V → 6×0.6=3.6V
BATTERY_VOLTAGE_FULL  = 3.1   # volts, CR2 fresh/nominal (for % calculation)
BATTERY_VOLTAGE_EMPTY = 2.1   # volts, CR2 end-of-life (for % calculation)
BATTERY_ADC_MAX       = 1024  # 10-bit ADC

# GATT poll interval
CONF_GATT_POLL_INTERVAL = "gatt_poll_interval"   # options key
GATT_POLL_INTERVAL_DEFAULT = 30                   # minutes (default)
GATT_POLL_INTERVAL_MIN = 5                        # minutes (minimum)
GATT_POLL_INTERVAL_MAX = 1440                     # minutes (24 hours)

# Device type discriminator in advertisement byte[3]
HT1_DEVICE_TYPE = 1
