import pyvisa as visa
import serial
import time
import csv

dev_cm = None
dev_target = None

DEBUG = False

# SCPI Addresses:
# Current source: USB, prologix USB-GPIB, address 1. Hence: not via pyvisa, as that is not stable for that adapter.
ADDR_SOURCE = "/dev/cu.usbmodem21401"
ADDR_SOURCE_SUBADDR = "1"
AUTOREAD = False
SERIAL_TIMEOUT = 0.1
# Calibrator:
ADDR_CALIBRATOR = "TCPIP::192.168.7.201::INSTR"
NPLC_MAX_CALIBRATOR = 100
MEASUREMENT_TYPE_CALIBRATOR = "VOLT:DC"
#MEASUREMENT_TYPE_CALIBRATOR = "CURR:DC"

# Target
ADDR_TARGET = "TCPIP::192.168.7.205::INSTR"
NPLC_MAX_TARGET = 10

AZERO = False
DISPLAY_OFF = False

OUTFILE = "out.csv"

# my shunts go to 2A
CURRENT_MAX = 2
# go 5% steps up. Easy way to get a close to logarithmic test.
CURRENT_STEPS_PERC = 5
# the HP 66332A only has 1mA resolution with about 0.5mA error margin.
CURRENT_RESOLUTION = 0.0005

# make sure you use valid values, for all devices.
MEASUREMENT_NPLC = 100


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
        
    inst_cal.write(f"CONF:{MEASUREMENT_TYPE_CALIBRATOR} {range}") # This messes up all of the below. So set it
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
        float,string: value read, range used
    """
    global inst_cal
    
    inst_cal.write("*WAI")
    s = inst_cal.query("FETCH?").strip()
    f = float(s)
    s = inst_cal.query(f"{MEASUREMENT_TYPE_CALIBRATOR}:RANG?")
    r = str(float(s)) # make it a simplified version. I tend to get stuff back like "+1.00000000E-01". Make it "0.1"
    return f, r


def inst_target_init(rm, channels=None):
    """Init the device

    Args:
        rm (ResourceManager): the global resource manager
        channels (array, optional): list of channels to use. None = front panel only. Defaults to None.

    Returns:
        Boolean: success
    """
    
    global inst_target
    inst_target = rm.open_resource(ADDR_TARGET)
    
    sChannels = ""
    if channels is not None and len(channels) > 0:
        sChannels = ", (@" + ','.join(channels) + ")"
        
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
    inst_target.write(f"VOLT:DC:AZER {s}"+sChannels)
    
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
        sChannel = f" (@{ch})"
            
    inst_target.write("ABOR")
    if ch != 0:
        inst_target.write("ROUT:OPEN:ALL")
        inst_target.write("ROUT:CLOS" + sChannel)
        
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
        float,string: value read, range used
    """
    global inst_target

    inst_target.write("*WAI")
    s = inst_target.query('FETCH? "defbuffer1", READ, CHAN, STAT').strip()
    r = inst_target.query("VOLT:DC:RANG?").strip() # this will be a nice short string
    if ch != 0:
        inst_target.write(f"ROUT:OPEN (@{ch})")
        inst_target.write("ROUT:OPEN:ALL")

    l = s.split(",")
    if len(l) != 3:
        print(f'ERROR reading from channel {ch}, reply = "{s}"')
        return None, r

    try:
        if ch != 0:
            if int(l[1]) != int(ch):
                print(f"ERROR reading from channel {ch}, got reply from channel {l[1]}")
                return None, r
        if int(l[2]) not in [0, 8]:
            print(f"ERROR reading from channel {ch}, got status code {l[2]}")
            return None, r
    except:
        print(f'ERROR reading from channel {ch}, reply = "{s}"')
        return None, r

    f = float(l[0])
    return f, r


def format_float(val):
    return f"{val:+.8f}".replace(".", ",")


def readDevices(test):
    global _inst_cal
    global inst_target

    print(f"Using NPLC {MEASUREMENT_NPLC}")

    rm = visa.ResourceManager()
    if DEBUG:
        print(rm.list_resources())

    print("Opening calibrator.")
    if not inst_cal_init(rm):
        return 1

    print("Opening target.")
    if not inst_target_init(rm):
        return 1
    
    ch = 0
    rc = "10"
    rt = "10"
    while True:
        # prepare
        cmdTriggerC = prepareMeasurement_inst_cal(rc)
        cmdTriggerT = prepareMeasurement_inst_target(ch, rt)
        
        # trigger together
        #t1 = time.perf_counter()
        inst_cal.write(cmdTriggerC)
        inst_target.write(cmdTriggerT)
        #t2 = time.perf_counter()
        #print(f"total trigger time: {int((t2-t1)*1000)}ms")

        # read results
        fc, rc = getMeasurement_inst_cal()
        ft, rt = getMeasurement_inst_target()
        print(f"{format_float(fc)} {rc} {format_float(ft)} {rt} dV={format_float(fc-ft)}")
    

if __name__ == "__main__":
    # set param to True to force a short test
    readDevices(False)
