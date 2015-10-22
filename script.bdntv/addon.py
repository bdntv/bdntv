import buggalo
import gui

buggalo.SUBMIT_URL = 'http://tommy.winther.nu/exception/submit.php'

try:
    w = gui.TVGuide()
    w.doModal()
    del w

except Exception:
    buggalo.onExceptionRaised()
