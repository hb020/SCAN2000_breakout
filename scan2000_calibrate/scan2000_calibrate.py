# SCAN2000 shunt linearity measurement
# via SCPI
# Current source: 4 Quadrant enabled HP 66332A (option 760, relay board)
# Current measurement/Calibrator: K34465A. Must have done a fresh ACAL before!
# Target: DMM6500 with SCAN2000-20, with shunts on channels 1 and 11

# How to use: connect the current source on the series connection of the current 
# measurement device + CH1 + CH11.
# This script walks through a range of current values, and measures the "real" current 
# and compares that to the voltage reading in the channels 1 and 11
# As the current source is somewhat noisy, it measures the current and the voltage simultaneously, and for the same duration.
# Since I cannot read channel 1 and 11 at the same time, I must do 2 measurement sets per current level set:
# one for channel 1, and one for channel 11.
#
# The result is a CSV file with (current in A, Voltage in V):
# "nr": line/test sequence number
# "set" the set current
# "actual1": current read while measuring channel 1 
# "actual11": current read while measuring channel 11 
# "ch1": voltage on channel 1
# "ch11": voltage on channel 11
# "avg_actual": average current read
# "abs_actual": average current read, absolute value
# "m_ch1": multiplication factor CH1: actual1/ch1
# "m_ch11": multiplication factor CH11: actual11/ch11
# "ch_range" range while reading voltage on ch1 and ch11. In case of a difference between the 2 measurements: average of the 2.
# "curr_range": range while reading current. In case of a difference between the 2 measurements: average of the 2.
#
# TODO: This script is robust against the/my? DMM6500's tendency to sometimes lose a command.

# TODO: sync the current measurements. Right now the results are noisy in low amps because the current source is noisy.
# TODO: do measurements with a 4 Quadrant enabled HP 6634B, as that has better low current behaviour

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
ADDR_SOURCE = "/dev/cu.usbmodem31401"
ADDR_SOURCE_SUBADDR = "1"
AUTOREAD = False
SERIAL_TIMEOUT = 0.1
# Calibrator:
ADDR_CALIBRATOR = "TCPIP::192.168.7.201::INSTR"
NPLC_MAX_CALIBRATOR = 100
# MEASUREMENT_TYPE_CALIBRATOR = "VOLT:DC"
MEASUREMENT_TYPE_CALIBRATOR = "CURR:DC"
# do autorange on calibrator. That clicks a lot.
AUTORANGE_CAL = False

# Target
ADDR_TARGET = "TCPIP::192.168.7.205::INSTR"
NPLC_MAX_TARGET = 10

# Switching off auto zero improves timing alignment of the measurements A LOT. It however introduces long term drift.
# So when using a noisy current source, do not do AZERO
AZERO = False
# Display OFF slightly improves speed
DISPLAY_OFF = False

OUTFILE = "out.csv"

# my shunts go to 2A
CURRENT_MAX = 2
# go 5% steps up. Easy way to get a close to logarithmic test.
CURRENT_STEPS_PERC = 5
# the HP 66332A only has 2mA programming accuracy with about 0.5mA error margin.
CURRENT_RESOLUTION = 0.001

# Set the aperture (expressed in PLC). Must be 1..NPLC_MAX_CALIBRATOR
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


def inst_cs_close():
    inst_cs_write("OUTP 0")
    inst_cs_write("OUTP:REL:POL NORM")
    inst_cs_write("SOUR:VOLT 0")
    inst_cs_write("SOUR:CURR 0")


def inst_cal_init(rm):
    """Init the device

    Args:
        rm (ResourceManager): the global resource manager

    Returns:
        Boolean: success
    """
    global inst_cal
    inst_cal = rm.open_resource(ADDR_CALIBRATOR)

    if MEASUREMENT_NPLC > 10:
        # in ms
        inst_cal.timeout = 10000

    inst_cal.write("*CLS")
    # check ID
    s = inst_cal.query("*IDN?").strip()
    if "34465A" not in s:
        print(f'ERROR: device ID is unexpected: "{s}"')
        return False

    # set to overall config
    inst_cal.write(f"CONF:{MEASUREMENT_TYPE_CALIBRATOR} AUTO")

    # improve for fast use:
    if DISPLAY_OFF:
        inst_cal.write("DISP OFF")

    s = inst_cal.query("SYST:ERR?").strip()
    if not s.startswith("+0"):
        print(f'ERROR during init: "{s}"')
        return False
    return True


def prepareMeasurement_inst_cal(range=None):
    """Prepare the measurement

    Args:
        range (String, optional): range to be set. When None: set to auto range. Defaults to None.

    Returns:
        String: the command to be sent to start the measurement
    """
    global inst_cal
    
    nplc = min(MEASUREMENT_NPLC, NPLC_MAX_CALIBRATOR)

    if range is None:
        nplc = 1
        range = "AUTO"
        
    inst_cal.write(f"CONF:{MEASUREMENT_TYPE_CALIBRATOR} {range}")  # This messes up all of the below. So set it
    if "CURR" in MEASUREMENT_TYPE_CALIBRATOR:
        inst_cal.write("SENS:CURR:DC:TERM 3")
    inst_cal.write(f"SENS:{MEASUREMENT_TYPE_CALIBRATOR}:NPLC {nplc}")
    if AZERO:
        s = "ON"
    else:
        s = "OFF"
    inst_cal.write(f"SENS:{MEASUREMENT_TYPE_CALIBRATOR}:ZERO:AUTO {s}")

    s = inst_cal.query("SYST:ERR?").strip()
    if not s.startswith("+0"):
        print(f'ERROR during prepareMeasurement: "{s}"')
        return None
                    
    # trigger options:
    # 1) TRIG:SOUR IMM ; INIT
    # 2) TRIG:SOUR BUS ; INIT ; *TRG
    inst_cal.write("TRIG:SOUR BUS")
    inst_cal.write("INIT")
    return "*TRG"
    

def getMeasurement_inst_cal():
    """Get the measurement values
    
    Returns:
        float,str: value read, range used
    """
    global inst_cal
    
    inst_cal.write("*WAI")
    s = inst_cal.query("FETCH?").strip()
    f = float(s)
    s = inst_cal.query(f"{MEASUREMENT_TYPE_CALIBRATOR}:RANG?")
    r = str(float(s))  # make it a simplified version. I tend to get stuff back like "+1.00000000E-01". Make it "0.1"
    return f, r


def inst_cal_close():
    inst_cal.write("DISP ON")
    inst_cal.write("SYST:LOCal")


def inst_target_init(rm, channels=None):
    """Init the device

    Args:
        rm (ResourceManager): the global resource manager
        channels (string, optional): list of channels to use. None = front panel only. Defaults to None.

    Returns:
        Boolean: success
    """

    global inst_target
    inst_target = rm.open_resource(ADDR_TARGET)
    
    sChannels = ""
    if channels is not None and len(channels) > 0:
        sChannels = ", (@" + channels + ")"
        
    if MEASUREMENT_NPLC > 10:
        # in ms
        inst_target.timeout = 10000

    inst_target.write("*CLS")

    # check ID
    s = inst_target.query("*IDN?").strip()
    if "DMM6500" not in s:
        print(f'ERROR: device ID is unexpected: "{s}"')
        return False

    # set to voltage measurement
    inst_target.write("SENS:FUNC 'VOLT'" + sChannels)
    inst_target.write("VOLT:DC:RANG:AUTO 1" + sChannels)
    inst_target.write("VOLT:DC:INP AUTO" + sChannels)
    inst_target.write("VOLT:DC:LINE:SYNC 0" + sChannels)
    if AZERO:
        s = "1"
    else:
        s = "0"
    inst_target.write(f"VOLT:DC:AZER {s}" + sChannels)
    
    # improve for fast use:
    if DISPLAY_OFF:
        inst_target.write("DISP:SCR PROC")
    
    s = inst_target.query("SYST:ERR?").strip()
    if not s.startswith("0,\"No error"):
        print(f'ERROR during init: "{s}"')
        return False
    return True


def prepareMeasurement_inst_target(ch=0, range=None):
    """Prepare the measurement

    Args:
        ch (int, optional): Channel to be used. 0 = front panel. Defaults to 0.
        range (String, optional): range to be set. When None: set to auto range. Defaults to None.

    Returns:
        String: the command to be sent to start the measurement
    """
    global inst_target
    # TODO: in rare cases, wildly off measurements get through. Check that.
    
    sChannel = ""
    if ch != 0:
        sChannel = f", (@{ch})"
            
    inst_target.write("ABOR")
    if ch != 0:
        inst_target.write("ROUT:OPEN:ALL")
        inst_target.write(f"ROUT:CLOS (@{ch})")  # without a comma, so directly
        
    nplc = MEASUREMENT_NPLC
    
    if range is None:
        nplc = 1
        inst_target.write("VOLT:DC:RANG:AUTO 1" + sChannel)
    else:
        inst_target.write("VOLT:DC:RANG " + range + sChannel)
        
    avg_filter = 1
    if nplc > NPLC_MAX_TARGET:
        nplc = NPLC_MAX_TARGET
        avg_filter = MEASUREMENT_NPLC / NPLC_MAX_TARGET
    
    inst_target.write(f"SENS:VOLT:NPLC {nplc}" + sChannel)
    
    if avg_filter <= 1:
        inst_target.write("VOLT:DC:AVER 0" + sChannel)
    else:
        inst_target.write(f"VOLT:DC:AVER:COUNT {avg_filter}" + sChannel)
        inst_target.write("VOLT:DC:AVER:TCON REP" + sChannel)
        inst_target.write("VOLT:DC:AVER:STAT 1" + sChannel)

    s = inst_target.query("SYST:ERR?").strip()
    if not s.startswith("0,\"No error"):
        print(f'ERROR during prepareMeasurement: "{s}"')
        return None

    # trigger options:
    # 1) TRIG:LOAD "SimpleLoop", 1 ; INIT
    # .. haven't found a way to use *TRG
    
    # set for immediate trigger
    inst_target.write("TRIG:LOAD \"SimpleLoop\", 1")    
    return "INIT"


def getMeasurement_inst_target(ch=0):
    """Get the measurement values

    Args:
        ch (int, optional): Channel to be used. 0 = front panel. Defaults to 0.
        
    Returns:
        float,str: value read, range used
    """
    global inst_target

    inst_target.write("*WAI")
    s = inst_target.query('FETCH? "defbuffer1", READ, CHAN, STAT').strip()
    r = inst_target.query("VOLT:DC:RANG?").strip()  # this will be a nice short string
    if ch != 0:
        inst_target.write(f"ROUT:OPEN (@{ch})")
        inst_target.write("ROUT:OPEN:ALL")

    ls = s.split(",")
    if len(ls) != 3:
        print(f'ERROR reading from channel {ch}, reply = "{s}"')
        return None, r

    try:
        if ch != 0:
            if int(ls[1]) != int(ch):
                print(f"ERROR reading from channel {ch}, got reply from channel {ls[1]}")
                return None, r
        if int(ls[2]) not in [0, 8]:
            print(f"ERROR reading from channel {ch}, got status code {ls[2]}")
            return None, r
    except:
        print(f'ERROR reading from channel {ch}, reply = "{s}"')
        return None, r

    f = float(ls[0])
    return f, r


def inst_target_close():
    inst_target.write("DISP:SCR HOME")


def initMeasurements():
    inst_cs_write("OUTP 1")
    # let CC mode activate
    time.sleep(1)
    

def closeMeasurements():
    inst_cs_close()
    inst_cal_close()
    inst_target_close()
    
    
def getMeasurement(ch=0, rc=None, rt=None):
    """ get a measurement that is synced in time between the calibrator and the target

    Args:
        ch (int, optional): Channel to be used. 0 = front panel. Defaults to 0.
        rc (str, optional): calibrator range to be set. When None: set to auto range. Defaults to None.
        rc (str, optional): target range to be set. When None: set to auto range. Defaults to None.

    Returns:
        float, str, float, str: cal value, cal range, target value, target range
    """
    skip_rc = (rc is not None) and (rt is None)

    # prepare
    if not skip_rc:
        cmdTriggerC = prepareMeasurement_inst_cal(rc)
    cmdTriggerT = prepareMeasurement_inst_target(ch, rt)
    
    # trigger together
    # t1 = time.perf_counter()
    if not skip_rc:
        inst_cal.write(cmdTriggerC)
    inst_target.write(cmdTriggerT)
    # t2 = time.perf_counter()
    # print(f"total trigger time: {int((t2-t1)*1000)}ms")

    # read results
    if not skip_rc:
        fc, rc = getMeasurement_inst_cal()
    else:
        fc = None
    ft, rt = getMeasurement_inst_target()
    return fc, rc, ft, rt


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


def format_float(val):
    return f"{val:+.8f}".replace(".", ",")


def readDevices(test):
    global inst_cm
    global inst_target

    print(f"Using NPLC {NPLC_MAX_TARGET}")

    rm = visa.ResourceManager()
    if DEBUG:
        print(rm.list_resources())
    print("Opening current source.")
    if not inst_cs_init():
        return 1

    print("Opening calibrator.")
    if not inst_cal_init(rm):
        return 1

    print("Opening target.")
    if not inst_target_init(rm, "1,11"):
        return 1

    print("Init OK")

    print("Creating values")

    if test:
        # DEBUG: force a short test
        vals = [0.0085]
    else:
        vals = [CURRENT_MAX, CURRENT_MAX * -1]
        v = CURRENT_RESOLUTION
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
            "actual1",
            "actual11",
            "ch1",
            "ch11",
            "avg_actual",
            "abs_actual",
            "m_ch1",
            "m_ch11",
            "ch_range",
            "curr_range",
        ]
                
        csvwriter = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=";")
        csvwriter.writeheader()

        initMeasurements()

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

            rc = None
            w = abs(float(v))
            if not AUTORANGE_CAL:
                # TODO make this configurable: even at 0, the current = 1.3mA, so 1mA range will not do.
#                if w <= 0.001:
#                    rc = 0.001
#                elif w <= 0.01:
                if w <= 0.01:
                    rc = 0.01
                elif w <= 0.1:
                    rc = 0.1
                elif w <= 1:
                    rc = 1
                else:
                    rc = 3
            # do autorange via a short test
            fc1, rc, ft1, rt = getMeasurement(1, rc, None)
            # fc1 and ft1 are ignored here. They will be read below.
            
            
            # use the range values found above for the 2 channels
            fc1, rc1, ft1, rt1 = getMeasurement(1, rc, rt)
            fc11, rc11, ft11, rt11 = getMeasurement(11, rc, rt)

            d["actual1"] = format_float(fc1)
            d["actual11"] = format_float(fc11)
            if fc1 is None or fc11 is None:
                avg_actual = None
            else:
                avg_actual = (fc1 + fc11) / 2
            d["avg_actual"] = format_float(avg_actual)
            d["abs_actual"] = format_float(abs(avg_actual))

            current_range = (float(rc1) + float(rc11)) / 2
            d["curr_range"] = format_float(current_range)
            ch_range = (float(rt1) + float(rt11)) / 2
            d["ch_range"] = format_float(ch_range)
            
            if ft1 is not None:
                d["ch1"] = format_float(ft1)
                d["m_ch1"] = format_float(fc1 / ft1)
            else:
                d["ch1"] = ""
                d["m_ch1"] = ""
            if ft11 is not None:
                d["ch11"] = format_float(ft11)
                d["m_ch11"] = format_float(fc11 / ft11)
            else:
                d["ch11"] = ""
                d["m_ch11"] = ""
            csvwriter.writerow(d)

        closeMeasurements()


if __name__ == "__main__":
    # set param to True to force a short test
    readDevices(False)
