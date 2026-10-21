@echo off
setlocal EnableDelayedExpansion
rem Turns the Orchestral Music mod on. Put FluidR3_GM.sf2 in this same folder first.
set "HERE=%~dp0"
if not exist "%HERE%FluidR3_GM.sf2" (
  echo Could not find FluidR3_GM.sf2 in %HERE%
  echo Unzip FluidR3_GM.zip and put FluidR3_GM.sf2 next to FFTARecomp.exe, then run this again.
  pause
  exit /b 1
)
set "SF=%HERE%FluidR3_GM.sf2"
set "SF=!SF:\=/!"
if not exist "%HERE%mods" mkdir "%HERE%mods"
set "OUT=%HERE%mods\state.toml"
type nul > "!OUT!"
>> "!OUT!" echo format_version = 1
>> "!OUT!" echo.
>> "!OUT!" echo [[package]]
>> "!OUT!" echo id = "ffta.enhancement.orchestra"
>> "!OUT!" echo version = "0.1.0"
>> "!OUT!" echo.
>> "!OUT!" echo [[package]]
>> "!OUT!" echo id = "ffta.enhancement.widescreen"
>> "!OUT!" echo version = "1.0.1"
>> "!OUT!" echo.
>> "!OUT!" echo [[feature]]
>> "!OUT!" echo package_id = "ffta.enhancement.orchestra"
>> "!OUT!" echo id = "orchestra"
>> "!OUT!" echo enabled = true
>> "!OUT!" echo.
>> "!OUT!" echo [[feature]]
>> "!OUT!" echo package_id = "ffta.enhancement.widescreen"
>> "!OUT!" echo id = "widescreen"
>> "!OUT!" echo enabled = true
>> "!OUT!" echo.
>> "!OUT!" echo [[asset]]
>> "!OUT!" echo package_id = "ffta.enhancement.orchestra"
>> "!OUT!" echo id = "soundfont"
>> "!OUT!" echo path = "!SF!"
echo Orchestral Music is now enabled. Start FFTARecomp.exe as usual.
echo To turn it off again, delete the file mods\state.toml.
pause
