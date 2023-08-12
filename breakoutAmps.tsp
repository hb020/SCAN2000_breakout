--Auto created configuration script
--Sat Aug 12 06:15:12 2023
--Model: DMM6500
--Firmware Version: 1.7.12b

-- set up channel settings for all slots

-- set up channel settings for slot 1
if (string.sub(slot[1].idn, 1, 4) == "2020") and (string.sub(slot[1].idn, 6, 11) != "Pseudo") then
	-- last recorded switch card for slot 1 is model 2020
	channel.setdmm("1", dmm.ATTR_MEAS_FUNCTION, dmm.FUNC_DC_VOLTAGE, dmm.ATTR_MEAS_NPLC, 10, dmm.ATTR_MEAS_APERTURE, 0.2, dmm.ATTR_MEAS_MATH_ENABLE, dmm.ON)
	channel.setdmm("1", dmm.ATTR_MEAS_MATH_FORMAT, dmm.MATH_MXB, dmm.ATTR_MEAS_MATH_MXB_BF, -2.6e-06, dmm.ATTR_MEAS_MATH_MXB_MF, 10.013)
	channel.setdmm("11", dmm.ATTR_MEAS_FUNCTION, dmm.FUNC_DC_VOLTAGE, dmm.ATTR_MEAS_NPLC, 10, dmm.ATTR_MEAS_APERTURE, 0.2, dmm.ATTR_MEAS_MATH_ENABLE, dmm.ON)
	channel.setdmm("11", dmm.ATTR_MEAS_MATH_FORMAT, dmm.MATH_MXB, dmm.ATTR_MEAS_MATH_MXB_BF, -4.2e-06, dmm.ATTR_MEAS_MATH_MXB_MF, 10)
	--channel.close("1")
end

-- set up Scan
if (string.sub(slot[1].idn, 1, 4) == "2020") then
	display.watchchannels = '1'

	scan.add("1,11")
	scan.monitor.channel = "1"
else
	display.input.prompt(display.BUTTONS_OK, "The saved setup cannot be fully applied because inserted cards are different from the saved setup.")
end