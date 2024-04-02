--Breakout panel setup script
--Date: 2024-04-01
--Model: DMM6500
--Firmware Version: 1.7.12b

-- This is for 50Hz systems. 

function setI(n, ac)

	if ac then
		func = dmm.FUNC_AC_VOLTAGE
	else
		func = dmm.FUNC_DC_VOLTAGE
	end
	if (n != 1) and (n != 11) then
		-- not channel 1 or 11: bail out
		setNone(n)
	else
		mf = 1
		bf = 0
		-- adapt the values to your device
		if n == 1 then
			mf = 10.013
			bf = -2.6e-06
		end
		if n == 11 then
			mf = 10.0
			bf = -4.2e-06
		end
		if ac then
			-- no DC offset when on AC
			bf = 0
		end
		s = string.format("%d",n)
		channel.setdmm(s, dmm.ATTR_MEAS_FUNCTION, func, dmm.ATTR_MEAS_MATH_ENABLE, dmm.ON)
		channel.setdmm(s, dmm.ATTR_MEAS_MATH_FORMAT, dmm.MATH_MXB, dmm.ATTR_MEAS_MATH_MXB_BF, bf, dmm.ATTR_MEAS_MATH_MXB_MF, mf)
		if func == dmm.FUNC_DC_VOLTAGE then
			channel.setdmm(s, dmm.ATTR_MEAS_NPLC, 10, dmm.ATTR_MEAS_APERTURE, 0.2)
		end
		scan.add(s)
	end
end

function setV(n, ac)
	if ac then
		func = dmm.FUNC_AC_VOLTAGE
	else
		func = dmm.FUNC_DC_VOLTAGE
	end

	if (n == 1) or (n == 11) then
		-- channel 1 or 11: bail out
		setNone(n)
	else
		s = string.format("%d",n)
		channel.setdmm(s, dmm.ATTR_MEAS_FUNCTION, func, dmm.ATTR_MEAS_MATH_ENABLE, dmm.OFF)
		if func == dmm.FUNC_DC_VOLTAGE then
			channel.setdmm(s, dmm.ATTR_MEAS_NPLC, 10, dmm.ATTR_MEAS_APERTURE, 0.2)
		end
		scan.add(s)
	end
end

function setNone(n)
	s = string.format("%d",n)
	channel.setdmm(s, dmm.ATTR_MEAS_FUNCTION, dmm.FUNC_NONE)
end


if dmm.terminals != dmm.TERMINALS_REAR then
	-- not that this is needed, but just in case...
	display.input.prompt(display.BUTTONS_CANCEL, "Switch to rear terminals first.")
	exit()
end

-- set up channel settings for slot 1
if (string.sub(slot[1].idn, 1, 4) != "2020") or (string.sub(slot[1].idn, 6, 11) == "Pseudo") then
	-- I only work on a 2020
	display.input.prompt(display.BUTTONS_CANCEL, "The scanner card is not of the right type.")
	exit()
end


-- Ask how many Volt channels must be opened
func_choice = display.input.option("What configuration?", "2 DCI", "2 DCI + 2 DCV", "2 DCI + 4 DCV", "2 DCI + 6 DCV", "2 DCI + 8 DCV", "2 ACI", "2 ACI + 2 ACV", "2 ACI + 4 ACV", "2 ACI + 6 ACV", "2 ACI + 8 ACV")
nr = 1
ac = false
if (not func_choice) or (func_choice == display.BUTTON_CANCEL) then
	exit()
end
if func_choice == display.BUTTON_OPTION1 then
	nr = 1
	ac = false
end
if func_choice == display.BUTTON_OPTION2 then
	nr = 2
	ac = false
end
if func_choice == display.BUTTON_OPTION3 then
	nr = 3
	ac = false
end
if func_choice == display.BUTTON_OPTION4 then
	nr = 4
	ac = false
end
if func_choice == display.BUTTON_OPTION5 then
	nr = 5
	ac = false
end
if func_choice == display.BUTTON_OPTION6 then
	nr = 1
	ac = true
end
if func_choice == display.BUTTON_OPTION7 then
	nr = 2
	ac = true
end
if func_choice == display.BUTTON_OPTION8 then
	nr = 3
	ac = true
end
if func_choice == display.BUTTON_OPTION9 then
	nr = 4
	ac = true
end
if func_choice == display.BUTTON_OPTION10 then
	nr = 5
	ac = true
end

horizontal_list = true
func_choice = display.input.option("What scan order?", "Horizontal", "Vertical")
if (not func_choice) or (func_choice == display.BUTTON_CANCEL) then
	exit()
end		
if func_choice == display.BUTTON_OPTION2 then
	horizontal_list = false
end

channel.open("allslots")
scan.create()

-- Horizontal list
for i = 1, 5 do
	if i == 1 then
		setI(i, ac)
	else
		if i <= nr then
			setV(i, ac)
		else
			setNone(i)
		end
	end
	if not horizontal_list then
		if i == 1 then
			setI(10 + i, ac)
		else
			if i <= nr then
				setV(10 + i, ac)
			else
				setNone(10 + i)
			end
		end
	end
end

if horizontal_list then
	for i = 1, 5 do
		if i == 1 then
			setI(10 + i, ac)
		else
			if i <= nr then
				setV(10 + i, ac)
			else
				setNone(10 + i)
			end
		end
	end
end

display.watchchannels = '1'
scan.monitor.channel = "1"

--print.scan.list()

exit()

