' Запускает .bat без чёрного окна (для задач по расписанию днём)
CreateObject("WScript.Shell").Run """" & WScript.Arguments(0) & """", 0, True
