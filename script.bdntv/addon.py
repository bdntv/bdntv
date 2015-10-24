#**************************************************************************************
#*   BDTV Script                                                                      *
#*   Created by: Andrew Barnes                                                        *
#*   Date: October/2015                                                               *
#*                                                                                    *
#**************************************************************************************

import gui

try:
    w = gui.TVGuide()
    w.doModal()
    del w

except Exception:
    import sys
    import traceback as tb
    (etype, value, traceback) = sys.exc_info()
    tb.print_exception(etype, value, traceback)
