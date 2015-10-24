#**************************************************************************************
#*   BDTV Script                                                                      *
#*   Created by: Andrew Barnes                                                        *
#*   Date: October/2015                                                               *
#*                                                                                    *
#**************************************************************************************

import datetime
import threading
import time

import xbmc
import xbmcgui
import urllib2

import source as src
import xbmcaddon

ADDON = xbmcaddon.Addon(id = 'script.bdntv')

DEBUG = False

MODE_EPG = 'EPG'
MODE_TV = 'TV'
MODE_OSD = 'OSD'

ACTION_LEFT = 1
ACTION_RIGHT = 2
ACTION_UP = 3
ACTION_DOWN = 4
ACTION_PAGE_UP = 5
ACTION_PAGE_DOWN = 6
ACTION_SELECT_ITEM = 7
ACTION_PARENT_DIR = 9
ACTION_PREVIOUS_MENU = 10
ACTION_SHOW_INFO = 11
ACTION_NEXT_ITEM = 14
ACTION_PREV_ITEM = 15

ACTION_MOUSE_WHEEL_UP = 104
ACTION_MOUSE_WHEEL_DOWN = 105
ACTION_MOUSE_MOVE = 107

KEY_NAV_BACK = 92
KEY_CONTEXT_MENU = 117
KEY_HOME = 159

CHANNELS_PER_PAGE = 9

HALF_HOUR = datetime.timedelta(minutes=30)

def debug(s):
    if DEBUG: xbmc.log(str(s), xbmc.LOGDEBUG)


class Point(object):
    def __init__(self):
        self.x = self.y = 0

    def __repr__(self):
        return 'Point(x=%d, y=%d)' % (self.x, self.y)


class EPGView(object):
    def __init__(self):
        self.top = self.left = self.right = self.bottom = self.width = self.cellHeight = 0


class ControlAndProgram(object):
    def __init__(self, control, program):
        self.control = control
        self.program = program


class TVGuide(xbmcgui.WindowXML):
    C_MAIN_DATE = 4000
    C_MAIN_TITLE = 4020
    C_MAIN_TIME = 4021
    C_MAIN_DESCRIPTION = 4022
    C_MAIN_IMAGE = 4023
    C_MAIN_LOGO = 4024
    C_MAIN_TIMEBAR = 4100
    C_MAIN_LOADING = 4200
    C_MAIN_LOADING_PROGRESS = 4201
    C_MAIN_LOADING_TIME_LEFT = 4202
    C_MAIN_LOADING_CANCEL = 4203
    C_MAIN_MOUSE_CONTROLS = 4300
    C_MAIN_MOUSE_HOME = 4301
    C_MAIN_MOUSE_LEFT = 4302
    C_MAIN_MOUSE_UP = 4303
    C_MAIN_MOUSE_DOWN = 4304
    C_MAIN_MOUSE_RIGHT = 4305
    C_MAIN_MOUSE_EXIT = 4306
    C_MAIN_BACKGROUND = 4600
    C_MAIN_EPG = 5000
    C_MAIN_EPG_VIEW_MARKER = 5001
    C_MAIN_OSD = 6000
    C_MAIN_OSD_TITLE = 6001
    C_MAIN_OSD_TIME = 6002
    C_MAIN_OSD_DESCRIPTION = 6003
    C_MAIN_OSD_CHANNEL_LOGO = 6004
    C_MAIN_OSD_CHANNEL_TITLE = 6005

    def __new__(cls):
        return super(TVGuide, cls).__new__(cls, 'script-tvguide-main.xml', ADDON.getAddonInfo('path'))

    def __init__(self):
        src.deleteDB()
        super(TVGuide, self).__init__()
        self.notification = None
        self.redrawingEPG = False
        self.isClosing = False
        self.controlAndProgramList = list()
        self.ignoreMissingControlIds = list()
        self.channelIdx = 0
        self.focusPoint = Point()
        self.epgView = EPGView()
        self.player = xbmc.Player()
        self.database = None

        self.mode = MODE_EPG
        self.currentChannel = None

        self.osdEnabled = True
        self.osdChannel = None
        self.osdProgram = None

        # find nearest half hour
        self.viewStartDate = datetime.datetime.today()
        self.viewStartDate -= datetime.timedelta(minutes=self.viewStartDate.minute % 30,
                                                 seconds=self.viewStartDate.second)

    def getControl(self, controlId):
        try:
            return super(TVGuide, self).getControl(controlId)
        except:
            if controlId in self.ignoreMissingControlIds:
                return None
            if not self.isClosing:
                self.close()
            return None

    def close(self):
        if not self.isClosing:
            self.isClosing = True
            if self.player.isPlaying():
                self.player.stop()
            if self.database:
                self.database.close(super(TVGuide, self).close)
            else:
                super(TVGuide, self).close()

    def onInit(self):
        self._hideControl(self.C_MAIN_MOUSE_CONTROLS, self.C_MAIN_OSD)
        self._showControl(self.C_MAIN_EPG, self.C_MAIN_LOADING)
        self.setControlLabel(self.C_MAIN_LOADING_TIME_LEFT, 'Loading of data already in progress...')
        self.setFocusId(self.C_MAIN_LOADING_CANCEL)

        control = self.getControl(self.C_MAIN_EPG_VIEW_MARKER)
        if control:
            left, top = control.getPosition()
            self.focusPoint.x = left
            self.focusPoint.y = top
            self.epgView.left = left
            self.epgView.top = top
            self.epgView.right = left + control.getWidth()
            self.epgView.bottom = top + control.getHeight()
            self.epgView.width = control.getWidth()
            self.epgView.cellHeight = control.getHeight() / CHANNELS_PER_PAGE

        try:
            self.database = src.Database()
        except src.SourceNotConfiguredException:
            self.onSourceNotConfigured()
            self.close()
            return
        self.database.initialize(self.onSourceInitialized, self.isSourceInitializationCancelled)
        self.updateTimebar()

    def onAction(self, action):
        debug('Mode is: %s' % self.mode)

        if self.mode == MODE_TV:
            self.onActionTVMode(action)
        elif self.mode == MODE_OSD:
            self.onActionOSDMode(action)
        elif self.mode == MODE_EPG:
            self.onActionEPGMode(action)

    def onActionTVMode(self, action):
        if action.getId() == ACTION_PAGE_UP:
            self._channelUp()

        elif action.getId() == ACTION_PAGE_DOWN:
            self._channelDown()

        elif not self.osdEnabled:
            pass  # skip the rest of the actions

        elif action.getId() in [ACTION_PARENT_DIR, KEY_NAV_BACK, KEY_CONTEXT_MENU, ACTION_PREVIOUS_MENU]:
            self.onRedrawEPG(self.channelIdx, self.viewStartDate)

        elif action.getId() == ACTION_SHOW_INFO:
            self._showOsd()

    def onActionOSDMode(self, action):
        if action.getId() == ACTION_SHOW_INFO:
            self._hideOsd()

        elif action.getId() in [ACTION_PARENT_DIR, KEY_NAV_BACK, KEY_CONTEXT_MENU, ACTION_PREVIOUS_MENU]:
            self._hideOsd()
            self.onRedrawEPG(self.channelIdx, self.viewStartDate)

        elif action.getId() == ACTION_SELECT_ITEM:
            if self.playChannel(self.osdChannel):
                self._hideOsd()

        elif action.getId() == ACTION_PAGE_UP:
            self._channelUp()
            self._showOsd()

        elif action.getId() == ACTION_PAGE_DOWN:
            self._channelDown()
            self._showOsd()

        elif action.getId() == ACTION_UP:
            self.osdChannel = self.database.getPreviousChannel(self.osdChannel)
            self.osdProgram = self.database.getCurrentProgram(self.osdChannel)
            self._showOsd()

        elif action.getId() == ACTION_DOWN:
            self.osdChannel = self.database.getNextChannel(self.osdChannel)
            self.osdProgram = self.database.getCurrentProgram(self.osdChannel)
            self._showOsd()

        elif action.getId() == ACTION_LEFT:
            previousProgram = self.database.getPreviousProgram(self.osdProgram)
            if previousProgram:
                self.osdProgram = previousProgram
                self._showOsd()

        elif action.getId() == ACTION_RIGHT:
            nextProgram = self.database.getNextProgram(self.osdProgram)
            if nextProgram:
                self.osdProgram = nextProgram
                self._showOsd()

    def onActionEPGMode(self, action):
        if action.getId() in [ACTION_PARENT_DIR, KEY_NAV_BACK, ACTION_PREVIOUS_MENU]:
            self.close()
            return

        elif action.getId() == ACTION_MOUSE_MOVE:
            self._showControl(self.C_MAIN_MOUSE_CONTROLS)
            return

        elif action.getId() == KEY_CONTEXT_MENU:
            if self.player.isPlaying():
                self._hideEpg()

        controlInFocus = None
        currentFocus = self.focusPoint
        try:
            controlInFocus = self.getFocus()
            if controlInFocus in [elem.control for elem in self.controlAndProgramList]:
                (left, top) = controlInFocus.getPosition()
                currentFocus = Point()
                currentFocus.x = left + (controlInFocus.getWidth() / 2)
                currentFocus.y = top + (controlInFocus.getHeight() / 2)
        except Exception:
            control = self._findControlAt(self.focusPoint)
            if control is None and len(self.controlAndProgramList) > 0:
                control = self.controlAndProgramList[0].control
            if control is not None:
                self.setFocus(control)
                return

        if action.getId() == ACTION_LEFT:
            self._left(currentFocus)
        elif action.getId() == ACTION_RIGHT:
            self._right(currentFocus)
        elif action.getId() == ACTION_UP:
            self._up(currentFocus)
        elif action.getId() == ACTION_DOWN:
            self._down(currentFocus)
        elif action.getId() == ACTION_NEXT_ITEM:
            self._nextDay()
        elif action.getId() == ACTION_PREV_ITEM:
            self._previousDay()
        elif action.getId() == ACTION_PAGE_UP:
            self._moveUp(CHANNELS_PER_PAGE)
        elif action.getId() == ACTION_PAGE_DOWN:
            self._moveDown(CHANNELS_PER_PAGE)
        elif action.getId() == ACTION_MOUSE_WHEEL_UP:
            self._moveUp(scrollEvent=True)
        elif action.getId() == ACTION_MOUSE_WHEEL_DOWN:
            self._moveDown(scrollEvent=True)
        elif action.getId() == KEY_HOME:
            self.viewStartDate = datetime.datetime.today()
            self.viewStartDate -= datetime.timedelta(minutes=self.viewStartDate.minute % 30,
                                                     seconds=self.viewStartDate.second)
            self.onRedrawEPG(self.channelIdx, self.viewStartDate)
        elif action.getId() in [KEY_CONTEXT_MENU] and controlInFocus is not None:
            program = self._getProgramFromControl(controlInFocus)
            
    def onClick(self, controlId):
        if controlId in [self.C_MAIN_LOADING_CANCEL, self.C_MAIN_MOUSE_EXIT]:
            self.close()
            return

        if self.isClosing:
            return

        if controlId == self.C_MAIN_MOUSE_HOME:
            self.viewStartDate = datetime.datetime.today()
            self.viewStartDate -= datetime.timedelta(minutes=self.viewStartDate.minute % 30, seconds=self.viewStartDate.second)
            self.onRedrawEPG(self.channelIdx, self.viewStartDate)
            return
        elif controlId == self.C_MAIN_MOUSE_LEFT:
            self.viewStartDate -= datetime.timedelta(hours=2)
            self.onRedrawEPG(self.channelIdx, self.viewStartDate)
            return
        elif controlId == self.C_MAIN_MOUSE_UP:
            self._moveUp(count=CHANNELS_PER_PAGE)
            return
        elif controlId == self.C_MAIN_MOUSE_DOWN:
            self._moveDown(count=CHANNELS_PER_PAGE)
            return
        elif controlId == self.C_MAIN_MOUSE_RIGHT:
            self.viewStartDate += datetime.timedelta(hours=2)
            self.onRedrawEPG(self.channelIdx, self.viewStartDate)
            return

        program = self._getProgramFromControl(self.getControl(controlId))
        if program is None:
            return
			
        self.playChannel(program.channel)

    def setFocusId(self, controlId):
        control = self.getControl(controlId)
        if control:
            self.setFocus(control)

    def setFocus(self, control):
        debug('setFocus %d' % control.getId())
        if control in [elem.control for elem in self.controlAndProgramList]:
            debug('Focus before %s' % self.focusPoint)
            (left, top) = control.getPosition()
            if left > self.focusPoint.x or left + control.getWidth() < self.focusPoint.x:
                self.focusPoint.x = left
            self.focusPoint.y = top + (control.getHeight() / 2)
            debug('New focus at %s' % self.focusPoint)

        super(TVGuide, self).setFocus(control)

    def onFocus(self, controlId):
        try:
            controlInFocus = self.getControl(controlId)
        except Exception:
            return

        program = self._getProgramFromControl(controlInFocus)
        if program is None:
            return

        self.setControlLabel(self.C_MAIN_TITLE, '[B]%s[/B]' % program.title)
        if program.startDate or program.endDate:
            self.setControlLabel(self.C_MAIN_TIME,
                                 '[B]%s - %s[/B]' % (self.formatTime(program.startDate), self.formatTime(program.endDate)))
        else:
            self.setControlLabel(self.C_MAIN_TIME, '')
        if program.description:
            description = program.description
        else:
            description = 'No description'
        self.setControlText(self.C_MAIN_DESCRIPTION, description)

        if program.channel.logo is not None:
            self.setControlImage(self.C_MAIN_LOGO, program.channel.logo)
        if program.imageSmall is not None:
            self.setControlImage(self.C_MAIN_IMAGE, program.imageSmall)

        if not self.osdEnabled and self.player.isPlaying():
            self.player.stop()

    def _left(self, currentFocus):
        control = self._findControlOnLeft(currentFocus)
        if control is not None:
            self.setFocus(control)
        elif control is None:
            self.viewStartDate -= datetime.timedelta(hours=2)
            self.focusPoint.x = self.epgView.right
            self.onRedrawEPG(self.channelIdx, self.viewStartDate, focusFunction=self._findControlOnLeft)

    def _right(self, currentFocus):
        control = self._findControlOnRight(currentFocus)
        if control is not None:
            self.setFocus(control)
        elif control is None:
            self.viewStartDate += datetime.timedelta(hours=2)
            self.focusPoint.x = self.epgView.left
            self.onRedrawEPG(self.channelIdx, self.viewStartDate, focusFunction=self._findControlOnRight)

    def _up(self, currentFocus):
        currentFocus.x = self.focusPoint.x
        control = self._findControlAbove(currentFocus)
        if control is not None:
            self.setFocus(control)
        elif control is None:
            self.focusPoint.y = self.epgView.bottom
            self.onRedrawEPG(self.channelIdx - CHANNELS_PER_PAGE, self.viewStartDate,
                             focusFunction=self._findControlAbove)

    def _down(self, currentFocus):
        currentFocus.x = self.focusPoint.x
        control = self._findControlBelow(currentFocus)
        if control is not None:
            self.setFocus(control)
        elif control is None:
            self.focusPoint.y = self.epgView.top
            self.onRedrawEPG(self.channelIdx + CHANNELS_PER_PAGE, self.viewStartDate,
                             focusFunction=self._findControlBelow)

    def _nextDay(self):
        self.viewStartDate += datetime.timedelta(days=1)
        self.onRedrawEPG(self.channelIdx, self.viewStartDate)

    def _previousDay(self):
        self.viewStartDate -= datetime.timedelta(days=1)
        self.onRedrawEPG(self.channelIdx, self.viewStartDate)

    def _moveUp(self, count=1, scrollEvent=False):
        if scrollEvent:
            self.onRedrawEPG(self.channelIdx - count, self.viewStartDate)
        else:
            self.focusPoint.y = self.epgView.bottom
            self.onRedrawEPG(self.channelIdx - count, self.viewStartDate, focusFunction=self._findControlAbove)

    def _moveDown(self, count=1, scrollEvent=False):
        if scrollEvent:
            self.onRedrawEPG(self.channelIdx + count, self.viewStartDate)
        else:
            self.focusPoint.y = self.epgView.top
            self.onRedrawEPG(self.channelIdx + count, self.viewStartDate, focusFunction=self._findControlBelow)

    def _channelUp(self):
        channel = self.database.getNextChannel(self.currentChannel)
        self.playChannel(channel)

    def _channelDown(self):
        channel = self.database.getPreviousChannel(self.currentChannel)
        self.playChannel(channel)

    def playChannel(self, channel):
        self.currentChannel = channel
        wasPlaying = self.player.isPlaying()
        req = src.MAINURL + 'getstream.php?token=%s&channel=%s' % (src.token,channel.title.replace(' ', '%20'))
        response = urllib2.urlopen(req)
        url = response.read()
        xbmc.executebuiltin("PlayMedia(%s,1)" % url) 

        if not wasPlaying:
            self._hideEpg()

        threading.Timer(1, self.waitForPlayBackStopped).start()
        self.osdProgram = self.database.getCurrentProgram(self.currentChannel)

        return #url is not None

    def waitForPlayBackStopped(self):
        for retry in range(0, 100):
            time.sleep(0.1)
            if self.player.isPlaying():
                break

        while self.player.isPlaying() and not xbmc.abortRequested and not self.isClosing:
            time.sleep(0.5)

        self.onPlayBackStopped()

    def _showOsd(self):
        if not self.osdEnabled:
            return

        if self.mode != MODE_OSD:
            self.osdChannel = self.currentChannel

        if self.osdProgram is not None:
            self.setControlLabel(self.C_MAIN_OSD_TITLE, '[B]%s[/B]' % self.osdProgram.title)
            if self.osdProgram.startDate or self.osdProgram.endDate:
                self.setControlLabel(self.C_MAIN_OSD_TIME, '[B]%s - %s[/B]' % (
                    self.formatTime(self.osdProgram.startDate), self.formatTime(self.osdProgram.endDate)))
            else:
                self.setControlLabel(self.C_MAIN_OSD_TIME, '')
            self.setControlText(self.C_MAIN_OSD_DESCRIPTION, self.osdProgram.description)
            self.setControlLabel(self.C_MAIN_OSD_CHANNEL_TITLE, self.osdChannel.title)
            if self.osdProgram.channel.logo is not None:
                self.setControlImage(self.C_MAIN_OSD_CHANNEL_LOGO, self.osdProgram.channel.logo)
            else:
                self.setControlImage(self.C_MAIN_OSD_CHANNEL_LOGO, '')

        self.mode = MODE_OSD
        self._showControl(self.C_MAIN_OSD)

    def _hideOsd(self):
        self.mode = MODE_TV
        self._hideControl(self.C_MAIN_OSD)

    def _hideEpg(self):
        self._hideControl(self.C_MAIN_EPG)
        self.mode = MODE_TV
        self._clearEpg()

    def onRedrawEPG(self, channelStart, startTime, focusFunction=None):
        if self.redrawingEPG or (self.database is not None and self.database.updateInProgress) or self.isClosing:
            debug('onRedrawEPG - already redrawing')
            return  # ignore redraw request while redrawing
        debug('onRedrawEPG')

        self.redrawingEPG = True
        self.mode = MODE_EPG
        self._showControl(self.C_MAIN_EPG)
        self.updateTimebar(scheduleTimer=False)

        # show Loading screen
        self.setControlLabel(self.C_MAIN_LOADING_TIME_LEFT, 'Calculating remaining time...')
        self._showControl(self.C_MAIN_LOADING)
        self.setFocusId(self.C_MAIN_LOADING_CANCEL)

        # remove existing controls
        self._clearEpg()

        try:
            self.channelIdx, channels, programs = self.database.getEPGView(channelStart, startTime, self.onSourceProgressUpdate, clearExistingProgramList=False)
        except src.SourceException:
            self.onEPGLoadError()
            return

        channelsWithoutPrograms = list(channels)

        # date and time row
        self.setControlLabel(self.C_MAIN_DATE, self.formatDate(self.viewStartDate))
        for col in range(1, 5):
            self.setControlLabel(4000 + col, self.formatTime(startTime))
            startTime += HALF_HOUR

        if programs is None:
            self.onEPGLoadError()
            return

        # set channel logo or text
        for idx in range(0, CHANNELS_PER_PAGE):
            if idx >= len(channels):
                self.setControlImage(4110 + idx, ' ')
                self.setControlLabel(4010 + idx, ' ')
            else:
                channel = channels[idx]
                self.setControlLabel(4010 + idx, channel.title)
                if channel.logo is not None:
                    self.setControlImage(4110 + idx, channel.logo)
                else:
                    self.setControlImage(4110 + idx, ' ')

        for program in programs:
            idx = channels.index(program.channel)
            if program.channel in channelsWithoutPrograms:
                channelsWithoutPrograms.remove(program.channel)

            startDelta = program.startDate - self.viewStartDate
            stopDelta = program.endDate - self.viewStartDate

            cellStart = self._secondsToXposition(startDelta.seconds)
            if startDelta.days < 0:
                cellStart = self.epgView.left
            cellWidth = self._secondsToXposition(stopDelta.seconds) - cellStart
            if cellStart + cellWidth > self.epgView.right:
                cellWidth = self.epgView.right - cellStart

            if cellWidth > 1:
                noFocusTexture = 'tvguide-program-grey.png'
                focusTexture = 'tvguide-program-grey-focus.png'

                if cellWidth < 25:
                    title = ''  # Text will overflow outside the button if it is too narrow
                else:
                    title = program.title

                control = xbmcgui.ControlButton(
                    cellStart,
                    self.epgView.top + self.epgView.cellHeight * idx,
                    cellWidth - 2,
                    self.epgView.cellHeight - 2,
                    title,
                    noFocusTexture=noFocusTexture,
                    focusTexture=focusTexture
                )

                self.controlAndProgramList.append(ControlAndProgram(control, program))

        for channel in channelsWithoutPrograms:
            idx = channels.index(channel)

            control = xbmcgui.ControlButton(
                self.epgView.left,
                self.epgView.top + self.epgView.cellHeight * idx,
                (self.epgView.right - self.epgView.left) - 2,
                self.epgView.cellHeight - 2,
                'No Program',
                noFocusTexture='tvguide-program-grey.png',
                focusTexture='tvguide-program-grey-focus.png'
            )

            program = src.Program(channel, 'No program available', None, None, None)
            self.controlAndProgramList.append(ControlAndProgram(control, program))

        # add program controls
        if focusFunction is None:
            focusFunction = self._findControlAt
        focusControl = focusFunction(self.focusPoint)
        controls = [elem.control for elem in self.controlAndProgramList]
        self.addControls(controls)
        if focusControl is not None:
            debug('onRedrawEPG - setFocus %d' % focusControl.getId())
            self.setFocus(focusControl)

        self.ignoreMissingControlIds.extend([elem.control.getId() for elem in self.controlAndProgramList])

        if focusControl is None and len(self.controlAndProgramList) > 0:
            self.setFocus(self.controlAndProgramList[0].control)

        self._hideControl(self.C_MAIN_LOADING)
        self.redrawingEPG = False

    def _clearEpg(self):
        controls = [elem.control for elem in self.controlAndProgramList]
        try:
            self.removeControls(controls)
        except RuntimeError:
            for elem in self.controlAndProgramList:
                try:
                    self.removeControl(elem.control)
                except RuntimeError:
                    pass  # happens if we try to remove a control that doesn't exist
        del self.controlAndProgramList[:]

    def onEPGLoadError(self):
        self.redrawingEPG = False
        self._hideControl(self.C_MAIN_LOADING)
        xbmcgui.Dialog().ok('Cannot load Guide', 'Please contact BDN Support,', 'to register your subscription.')
        self.close()

    def onSourceNotConfigured(self):
        self.redrawingEPG = False
        self._hideControl(self.C_MAIN_LOADING)
        xbmcgui.Dialog().ok('Cannot load Guide', 'Please contact BDN Support,', 'to register your subscription.')
        self.close()

    def isSourceInitializationCancelled(self):
        return xbmc.abortRequested or self.isClosing

    def onSourceInitialized(self, success):
        if success:
            self.onRedrawEPG(0, self.viewStartDate)

    def onSourceProgressUpdate(self, percentageComplete):
        control = self.getControl(self.C_MAIN_LOADING_PROGRESS)
        if percentageComplete < 1:
            if control:
                control.setPercent(1)
            self.progressStartTime = datetime.datetime.now()
            self.progressPreviousPercentage = percentageComplete
        elif percentageComplete != self.progressPreviousPercentage:
            if control:
                control.setPercent(percentageComplete)
            self.progressPreviousPercentage = percentageComplete
            delta = datetime.datetime.now() - self.progressStartTime

            if percentageComplete < 20:
                self.setControlLabel(self.C_MAIN_LOADING_TIME_LEFT, 'Calculating remaining time...')
            else:
                secondsLeft = int(delta.seconds) / float(percentageComplete) * (100.0 - percentageComplete)
                if secondsLeft > 30:
                    secondsLeft -= secondsLeft % 10
                self.setControlLabel(self.C_MAIN_LOADING_TIME_LEFT, 'Approximately %d seconds left...' % secondsLeft)

        return not xbmc.abortRequested and not self.isClosing

    def onPlayBackStopped(self):
        if not self.player.isPlaying() and not self.isClosing:
            self._hideControl(self.C_MAIN_OSD)
            self.onRedrawEPG(self.channelIdx, self.viewStartDate)

    def _secondsToXposition(self, seconds):
        return self.epgView.left + (seconds * self.epgView.width / 7200)

    def _findControlOnRight(self, point):
        distanceToNearest = 10000
        nearestControl = None

        for elem in self.controlAndProgramList:
            control = elem.control
            (left, top) = control.getPosition()
            x = left + (control.getWidth() / 2)
            y = top + (control.getHeight() / 2)

            if point.x < x and point.y == y:
                distance = abs(point.x - x)
                if distance < distanceToNearest:
                    distanceToNearest = distance
                    nearestControl = control

        return nearestControl

    def _findControlOnLeft(self, point):
        distanceToNearest = 10000
        nearestControl = None

        for elem in self.controlAndProgramList:
            control = elem.control
            (left, top) = control.getPosition()
            x = left + (control.getWidth() / 2)
            y = top + (control.getHeight() / 2)

            if point.x > x and point.y == y:
                distance = abs(point.x - x)
                if distance < distanceToNearest:
                    distanceToNearest = distance
                    nearestControl = control

        return nearestControl

    def _findControlBelow(self, point):
        nearestControl = None

        for elem in self.controlAndProgramList:
            control = elem.control
            (leftEdge, top) = control.getPosition()
            y = top + (control.getHeight() / 2)

            if point.y < y:
                rightEdge = leftEdge + control.getWidth()
                if leftEdge <= point.x < rightEdge and (nearestControl is None or nearestControl.getPosition()[1] > top):
                    nearestControl = control

        return nearestControl

    def _findControlAbove(self, point):
        nearestControl = None
        for elem in self.controlAndProgramList:
            control = elem.control
            (leftEdge, top) = control.getPosition()
            y = top + (control.getHeight() / 2)

            if point.y > y:
                rightEdge = leftEdge + control.getWidth()
                if leftEdge <= point.x < rightEdge and (nearestControl is None or nearestControl.getPosition()[1] < top):
                    nearestControl = control

        return nearestControl

    def _findControlAt(self, point):
        for elem in self.controlAndProgramList:
            control = elem.control
            (left, top) = control.getPosition()
            bottom = top + control.getHeight()
            right = left + control.getWidth()

            if left <= point.x <= right and top <= point.y <= bottom:
                return control

        return None

    def _getProgramFromControl(self, control):
        for elem in self.controlAndProgramList:
            if elem.control == control:
                return elem.program
        return None

    def _hideControl(self, *controlIds):
        """
        Visibility is inverted in skin
        """
        for controlId in controlIds:
            control = self.getControl(controlId)
            if control:
                control.setVisible(True)

    def _showControl(self, *controlIds):
        """
        Visibility is inverted in skin
        """
        for controlId in controlIds:
            control = self.getControl(controlId)
            if control:
                control.setVisible(False)

    def formatTime(self, timestamp):
        if timestamp:
            format = xbmc.getRegion('time').replace(':%S', '').replace('%H%H', '%H')
            return timestamp.strftime(format)
        else:
            return ''

    def formatDate(self, timestamp):
        if timestamp:
            format = xbmc.getRegion('dateshort')
            return timestamp.strftime(format)
        else:
            return ''

    def setControlImage(self, controlId, image):
        control = self.getControl(controlId)
        if control:
            control.setImage(image.encode('utf-8'))

    def setControlLabel(self, controlId, label):
        control = self.getControl(controlId)
        if control and label:
            control.setLabel(label)

    def setControlText(self, controlId, text):
        control = self.getControl(controlId)
        if control:
            control.setText(text)

    def updateTimebar(self, scheduleTimer=True):
        # move timebar to current time
        timeDelta = datetime.datetime.today() - self.viewStartDate
        control = self.getControl(self.C_MAIN_TIMEBAR)
        if control:
            (x, y) = control.getPosition()
            try:
                control.setVisible(timeDelta.days == 0)
            except:
                pass
            control.setPosition(self._secondsToXposition(timeDelta.seconds), y)

        if scheduleTimer and not xbmc.abortRequested and not self.isClosing:
            threading.Timer(1, self.updateTimebar).start()

class PopupMenu(xbmcgui.WindowXMLDialog):
    C_POPUP_PLAY = 4000
    C_POPUP_CHOOSE_STREAM = 4001
    C_POPUP_REMIND = 4002
    C_POPUP_CHANNELS = 4003
    C_POPUP_QUIT = 4004
    C_POPUP_CHANNEL_LOGO = 4100
    C_POPUP_CHANNEL_TITLE = 4101
    C_POPUP_PROGRAM_TITLE = 4102

    def __new__(cls, database, program, showRemind):
        return super(PopupMenu, cls).__new__(cls, 'script-tvguide-menu.xml', ADDON.getAddonInfo('path'))

    def __init__(self, database, program, showRemind):
        """

        @type database: source.Database
        @param program:
        @type program: source.Program
        @param showRemind:
        """
        super(PopupMenu, self).__init__()
        self.database = database
        self.program = program
        self.showRemind = showRemind
        self.buttonClicked = None

    def onInit(self):
        playControl = self.getControl(self.C_POPUP_PLAY)
        remindControl = self.getControl(self.C_POPUP_REMIND)
        channelLogoControl = self.getControl(self.C_POPUP_CHANNEL_LOGO)
        channelTitleControl = self.getControl(self.C_POPUP_CHANNEL_TITLE)
        programTitleControl = self.getControl(self.C_POPUP_PROGRAM_TITLE)

        playControl.setLabel('Watch %s', self.program.channel.title)
        if not self.program.channel.isPlayable():
            playControl.setEnabled(False)
            self.setFocusId(self.C_POPUP_CHOOSE_STREAM)
        if self.database.getCustomStreamUrl(self.program.channel):
            chooseStrmControl = self.getControl(self.C_POPUP_CHOOSE_STREAM)
            chooseStrmControl.setLabel('Remove stream file')

        if self.program.channel.logo is not None:
            channelLogoControl.setImage(self.program.channel.logo)
            channelTitleControl.setVisible(False)
        else:
            channelTitleControl.setLabel(self.program.channel.title)
            channelLogoControl.setVisible(False)

        programTitleControl.setLabel(self.program.title)

        if self.program.startDate:
            remindControl.setEnabled(True)
            if self.showRemind:
                remindControl.setLabel('Remind')
            else:
                remindControl.setLabel('Dont remind')
        else:
            remindControl.setEnabled(False)

    def onAction(self, action):
        if action.getId() in [ACTION_PARENT_DIR, ACTION_PREVIOUS_MENU, KEY_NAV_BACK, KEY_CONTEXT_MENU]:
            self.close()
            return

    def onClick(self, controlId):
        if controlId == self.C_POPUP_CHOOSE_STREAM and self.database.getCustomStreamUrl(self.program.channel):
            self.database.deleteCustomStreamUrl(self.program.channel)
            chooseStrmControl = self.getControl(self.C_POPUP_CHOOSE_STREAM)
            chooseStrmControl.setLabel('Choose stream')

            if not self.program.channel.isPlayable():
                playControl = self.getControl(self.C_POPUP_PLAY)
                playControl.setEnabled(False)

        else:
            self.buttonClicked = controlId
            self.close()

    def onFocus(self, controlId):
        pass


class ChannelsMenu(xbmcgui.WindowXMLDialog):
    C_CHANNELS_LIST = 6000
    C_CHANNELS_SELECTION_VISIBLE = 6001
    C_CHANNELS_SELECTION = 6002
    C_CHANNELS_SAVE = 6003
    C_CHANNELS_CANCEL = 6004

    def __new__(cls, database):
        return super(ChannelsMenu, cls).__new__(cls, 'script-tvguide-channels.xml', ADDON.getAddonInfo('path'))

    def __init__(self, database):
        """

        @type database: source.Database
        """
        super(ChannelsMenu, self).__init__()
        self.database = database
        self.channelList = database.getChannelList(onlyVisible=False)
        self.swapInProgress = False

    def onInit(self):
        self.updateChannelList()
        self.setFocusId(self.C_CHANNELS_LIST)

    def onAction(self, action):
        if action.getId() in [ACTION_PARENT_DIR, ACTION_PREVIOUS_MENU, KEY_NAV_BACK, KEY_CONTEXT_MENU]:
            self.close()
            return

        if self.getFocusId() == self.C_CHANNELS_LIST and action.getId() == ACTION_LEFT:
            listControl = self.getControl(self.C_CHANNELS_LIST)
            idx = listControl.getSelectedPosition()
            buttonControl = self.getControl(self.C_CHANNELS_SELECTION)
            buttonControl.setLabel('[B]%s[/B]' % self.channelList[idx].title)

            self.getControl(self.C_CHANNELS_SELECTION_VISIBLE).setVisible(False)
            self.setFocusId(self.C_CHANNELS_SELECTION)

        elif self.getFocusId() == self.C_CHANNELS_SELECTION and action.getId() in [ACTION_RIGHT, ACTION_SELECT_ITEM]:
            self.getControl(self.C_CHANNELS_SELECTION_VISIBLE).setVisible(True)
            xbmc.sleep(350)
            self.setFocusId(self.C_CHANNELS_LIST)

        elif self.getFocusId() == self.C_CHANNELS_SELECTION and action.getId() == ACTION_UP:
            listControl = self.getControl(self.C_CHANNELS_LIST)
            idx = listControl.getSelectedPosition()
            if idx > 0:
                self.swapChannels(idx, idx - 1)

        elif self.getFocusId() == self.C_CHANNELS_SELECTION and action.getId() == ACTION_DOWN:
            listControl = self.getControl(self.C_CHANNELS_LIST)
            idx = listControl.getSelectedPosition()
            if idx < listControl.size() - 1:
                self.swapChannels(idx, idx + 1)

    def onClick(self, controlId):
        if controlId == self.C_CHANNELS_LIST:
            listControl = self.getControl(self.C_CHANNELS_LIST)
            item = listControl.getSelectedItem()
            channel = self.channelList[int(item.getProperty('idx'))]
            channel.visible = not channel.visible

            if channel.visible:
                iconImage = 'tvguide-channel-visible.png'
            else:
                iconImage = 'tvguide-channel-hidden.png'
            item.setIconImage(iconImage)

        elif controlId == self.C_CHANNELS_SAVE:
            self.database.saveChannelList(self.close, self.channelList)

        elif controlId == self.C_CHANNELS_CANCEL:
            self.close()

    def onFocus(self, controlId):
        pass

    def updateChannelList(self):
        listControl = self.getControl(self.C_CHANNELS_LIST)
        listControl.reset()
        for idx, channel in enumerate(self.channelList):
            if channel.visible:
                iconImage = 'tvguide-channel-visible.png'
            else:
                iconImage = 'tvguide-channel-hidden.png'

            item = xbmcgui.ListItem('%3d. %s' % (idx + 1, channel.title), iconImage=iconImage)
            item.setProperty('idx', str(idx))
            listControl.addItem(item)

    def updateListItem(self, idx, item):
        channel = self.channelList[idx]
        item.setLabel('%3d. %s' % (idx + 1, channel.title))

        if channel.visible:
            iconImage = 'tvguide-channel-visible.png'
        else:
            iconImage = 'tvguide-channel-hidden.png'
        item.setIconImage(iconImage)
        item.setProperty('idx', str(idx))

    def swapChannels(self, fromIdx, toIdx):
        if self.swapInProgress:
            return
        self.swapInProgress = True

        c = self.channelList[fromIdx]
        self.channelList[fromIdx] = self.channelList[toIdx]
        self.channelList[toIdx] = c

        # recalculate weight
        for idx, channel in enumerate(self.channelList):
            channel.weight = idx

        listControl = self.getControl(self.C_CHANNELS_LIST)
        self.updateListItem(fromIdx, listControl.getListItem(fromIdx))
        self.updateListItem(toIdx, listControl.getListItem(toIdx))

        listControl.selectItem(toIdx)
        xbmc.sleep(50)
        self.swapInProgress = False