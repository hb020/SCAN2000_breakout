# SCAN2000 shunt linearity measurement
# via SCPI
# Current source: 4 Quadrant enabled HP 66332A (option 760, relay board)
# Current measurement: K34465A
# Target: DMM6500 with SCAN2000-20, with shunts on channels 1 and 11

import pyvisa as visa
import serial
import time
import csv

# the global vars of the devices
ser = serial.Serial()
dev_cm = None
dev_target = None

DEBUG = False

# SCPI Addresses:
# Current source: USB, prologix USB-GPIB, address 1. Hence: not via pyvisa, as that is not stable for that adapter.
ADDR_SOURCE = "/dev/cu.usbmodem1401"
ADDR_SOURCE_SUBADDR = "1"
AUTOREAD = False
SERIAL_TIMEOUT = 0.1
# Current measurement:
ADDR_CURRENTMEAURE = "TCPIP::192.168.7.201::INSTR"
NPLC_MAX_CURRENTMEASURE = 100
# Target
ADDR_TARGET = "TCPIP::192.168.7.205::INSTR"
NPLC_MAX_TARGET = 10

OUTFILE = "out.csv"

# my shunts go to 2A
CURRENT_MAX = 2
# go 5% steps up. Easy way to get a close to logarithmic test.
CURRENT_STEPS_PERC = 5
# the HP 66332A only has 1mA resolution with about 0.5mA error margin.
CURRENT_RESOLUTION = 0.0005

# make sure you use valid values, for all devices.
MEASUREMENT_NPLC = 10


def sendSerialCmdRaw(cmd):
    bcmd = bytearray()
    bcmd.extend(cmd.encode("ascii"))
    bcmd.append(0x0D)  # CR
    bcmd.append(0x0A)  # LF
    ser.write(bcmd)


def sendSerialCmd(cmd, readReply=True, delaysecs=0):
    global ser
    if DEBUG:
        if not readReply:
            print(f"Sending: {cmd}")
        else:
            print(f"Sending: {cmd} : ", end="")
    sendSerialCmdRaw(cmd)
    if readReply:
        if delaysecs > 0:
            time.sleep(delaysecs)
        if not AUTOREAD:
            sendSerialCmdRaw("++read eoi")
        s = ser.read(256)
        retstr = s.decode("ascii")
        if DEBUG:
            print(f"{retstr} ({len(s)}b)")
        return retstr
    else:
        s = ser.read(256)
        return None


def inst_cs_query(cmd):
    return sendSerialCmd(cmd, True)


def inst_cs_write(cmd):
    return sendSerialCmd(cmd, False)


def inst_cs_init():
    global ser

    port = ADDR_SOURCE
    addr = ADDR_SOURCE_SUBADDR
    baudrate = 38400  # 115200

    ser = serial.Serial(port, baudrate=baudrate, timeout=SERIAL_TIMEOUT)

    sendSerialCmd("++mode 1", False)  # controller mode (the only mode it supports)
    if AUTOREAD:
        sendSerialCmd("++auto 1", False)  # no need for "++read eoi"
    else:
        sendSerialCmd("++auto 0", False)  # need for "++read eoi"
    sendSerialCmd("++eos 0", False)  # CR/LF is oes
    sendSerialCmd("++addr " + addr, False)
    sendSerialCmd("++read", False)

    inst_cs_write("*CLS")
    # check ID
    s = inst_cs_query("*IDN?").strip()
    if "66332A" not in s:
        print(f'ERROR: device ID is unexpected: "{s}"')
        return False

    # output off, voltage 2V, current 0
    inst_cs_write("OUTP 0")
    inst_cs_write("OUTP:REL:POL NORM")
    inst_cs_write("SOUR:VOLT 10")
    inst_cs_write("SOUR:CURR 0")
    s = inst_cs_query("SYST:ERR?").strip()
    if not s.startswith("+0"):
        print(f'ERROR during init: "{s}"')
        return False

    return True


def inst_cm_init(rm):
    global inst_cm
    inst_cm = rm.open_resource(ADDR_CURRENTMEAURE)

    nplc = MEASUREMENT_NPLC
    if nplc > NPLC_MAX_CURRENTMEASURE:
        nplc = NPLC_MAX_CURRENTMEASURE

    if nplc > 10:
        # in ms
        inst_cm.timeout = 10000

    inst_cm.write("*CLS")
    # check ID
    s = inst_cm.query("*IDN?").strip()
    if "34465A" not in s:
        print(f'ERROR: device ID is unexpected: "{s}"')
        return False

    # set to current measurement, 3A range, auto
    inst_cm.write("CONF:CURR:DC AUTO")
    inst_cm.write("SENS:CURR:DC:TERM 3")
    inst_cm.write(f"SENS:CURR:DC:NPLC {nplc}")

    s = inst_cm.query("SYST:ERR?").strip()
    if not s.startswith("+0"):
        print(f'ERROR during init: "{s}"')
        return False
    return True


def inst_target_init(rm):
    global inst_target
    inst_target = rm.open_resource(ADDR_TARGET)

    nplc = MEASUREMENT_NPLC
    avg_filter = 1
    if nplc > NPLC_MAX_TARGET:
        nplc = NPLC_MAX_TARGET
        avg_filter = MEASUREMENT_NPLC / NPLC_MAX_TARGET
        # in ms
        inst_target.timeout = 10000

    inst_target.write("*CLS")
    
    # check ID
    s = inst_target.query("*IDN?").strip()
    if "DMM6500" not in s:
        print(f'ERROR: device ID is unexpected: "{s}"')
        return False

    # set to voltage measurement, inputs 1 and 11
    inst_target.write("SENS:FUNC 'VOLT', (@1,11)")
    inst_target.write(f"SENS:VOLT:NPLC {nplc}, (@1,11)")
    inst_target.write("VOLT:DC:RANG:AUTO 1, (@1,11)")
    inst_target.write("VOLT:DC:INP AUTO, (@1,11)")
    inst_target.write("VOLT:DC:LINE:SYNC 1, (@1,11)")
    if avg_filter <= 1:
        inst_target.write("VOLT:DC:AVER 0, (@1,11)")
    else:
        inst_target.write(f"VOLT:DC:AVER:COUNT {avg_filter}, (@1,11)")
        inst_target.write("VOLT:DC:AVER:TCON REP, (@1,11)")
        inst_target.write("VOLT:DC:AVER 1, (@1,11)")

    # TODO: this does not seem to work, even with SCPI syntax errors I get through
    s = inst_cm.query("SYST:ERR?").strip()
    if not s.startswith("+0"):
        print(f'ERROR during init: "{s}"')
        return False
    return True


def getTargetCh(ch):
    global inst_target

    # TODO: in rare cases, wildly off measurements get through. Check that.
    inst_target.write(f"ROUT:CLOS (@{ch})")
    s = inst_target.query("READ?").strip()
    inst_target.write(f"ROUT:OPEN (@{ch})")
    f = float(s)
    return f


def initMeasurements():
    inst_cs_write("OUTP 1")
    # let CC mode activate
    time.sleep(1)


def closeMeasurements():
    inst_cs_write("OUTP 0")
    inst_cs_write("OUTP:REL:POL NORM")
    inst_cs_write("SOUR:VOLT 0")
    inst_cs_write("SOUR:CURR 0")


# sets the current, and lets the PSU settle some time. This PSU has a tendency to take time to go to CC mode.
def setCurrent(val, oldval=None):
    sleeptime_s = 0.1
    if val < 0:
        if oldval is None or oldval >= 0:
            inst_cs_write("OUTP:REL:POL REV")
            sleeptime_s += 0.4
        val = abs(val)
    else:
        if oldval is None or oldval < 0:
            inst_cs_write("OUTP:REL:POL NORM")
            sleeptime_s += 0.4

    inst_cs_write(f"SOUR:CURR {val:.5f}")
    time.sleep(sleeptime_s)


def getCurrent():
    global inst_cm
    s = inst_cm.query("READ?").strip()
    f = float(s)
    return f


def format_float(val):
    return f"{val:+.8f}".replace(".", ",")


def initDevices():
    global inst_cm
    global inst_target

    rm = visa.ResourceManager()
    if DEBUG:
        print(rm.list_resources())
    print("Opening current source.")
    if not inst_cs_init():
        return 1

    print("Opening current measurement.")
    if not inst_cm_init(rm):
        return 1

    print("Opening target.")
    if not inst_target_init(rm):
        return 1

    print("Init OK")

    print("Creating values")

    vals = [CURRENT_MAX, CURRENT_MAX * -1]
    v = 0
    while v < CURRENT_MAX:
        vals.append(v)
        vals.append(-1 * v)
        s = v * CURRENT_STEPS_PERC / 100
        if s < CURRENT_RESOLUTION:
            s = CURRENT_RESOLUTION
        v += s

    vals.sort()

    print(f"Measuring over {len(vals)} values.")

    outfile = OUTFILE
    print(f'Logging results to CSV file "{outfile}".')
    with open(outfile, "w", newline="") as csvfile:
        fieldnames = [
            "nr",
            "set",
            "actual",
            "ch1",
            "ch11",
            "abs_actual",
            "m_ch1",
            "m_ch11",
        ]
        csvwriter = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=";")
        csvwriter.writeheader()

        initMeasurements()

        # DEBUG: force a short test
        # vals = [0.0085]

        my_max = len(vals)
        oldval = None
        for i in range(my_max):
            d = {}
            d["nr"] = i
            v = vals[i]
            d["set"] = format_float(v)
            print(f"{i:3d}/{my_max:3d}: {format_float(v)}")
            setCurrent(v, oldval)
            oldval = v

            f = getCurrent()
            ch1 = getTargetCh(1)
            ch11 = getTargetCh(11)

            d["actual"] = format_float(f)
            d["ch1"] = format_float(ch1)
            d["ch11"] = format_float(ch11)
            d["abs_actual"] = format_float(abs(f))
            d["m_ch1"] = format_float(f / ch1)
            d["m_ch11"] = format_float(f / ch11)
            csvwriter.writerow(d)

        closeMeasurements()


if __name__ == "__main__":
    initDevices()
