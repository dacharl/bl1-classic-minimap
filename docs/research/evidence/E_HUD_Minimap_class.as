    03f7: if !!_global.Minimap goto off +4561
    function () {
      03f9: r1()
    }
    0423: r1 = ?
    0427: ?[?] = ?
    043a: _global.Minimap extends MovieClip
    0443: r2 = r1.prototype
    function (clip, x, y, rot) {
      0405: <StringExtract >
      0406: eval(this.pathLen) = -1
      041d: var Obj = eval(((this + '.') + clip))
      042c: if !!(Obj == undefined) goto off +13
      0431: !(Obj == undefined)
      043f: if !Obj._visible goto off +289
      0487: <SetProperty >
      04cb: <SetProperty >
      04e2: if !(Obj._currentframe == 1) goto off +126
      04f5: if !!(rot == undefined) goto off +30
      04fa: !(rot == undefined)
      0519: if !!(clip.indexOf('.player') == -1) goto off +71
      053f: this.SetCurrentRotation((0.0 - rot))
      054e: if !!this.bRotateMinimap goto off +18
      0564: <SetProperty >
    }
    05e0: Obj[10.0] = rot
    function (clip, x, y, r, label, frame, frameVisible) {
      0405: if !(this.maps._currentframe == 1) goto off +6
      040f: return ''
      042d: var NHD = this.maps.getNextHighestDepth()
      043d: var newClip = (label + NHD)
      0454: var srcClip = eval(((this + '.') + clip))
      0474: var newObject = srcClip.duplicateMovieClip(newClip, NHD)
      048c: newObject.gotoAndStop(frame)
      0494: if !newObject goto off +360
      04a1: <TargetPath >
      04a2: newClip = newObject
      04b1: newObject._visible = frameVisible
      04db: this.UpdateLandmark(newClip, x, y, r)
      04e9: if !(frame == 'player') goto off +20
      04fc: this.playerClip = newObject
      04fd: goto off +178
      050f: if !(frame == 'waypoint') goto off +47
      0522: this.waypointClip = newObject
      053d: this.customWaypointMC._alpha = 0.0
      053e: goto off +113
      0550: if !(frame == 'objective') goto off +47
      0563: this.currentObjectiveClip = newObject
      057e: this.currentObjectiveMC._alpha = 0.0
      057f: goto off +48
      0591: if !this.playerClip goto off +30
      05b3: this.playerClip.swapDepths(newObject)
      05c6: if !(this.iconPathArray == undefined) goto off +24
      05e2: this.iconPathArray = new Array()
      0600: this.iconPathArray.push(newObject)
      0607: return newClip
    }
    0833: ?[?] = ?
    function (mapLabel) {
      03fe: r1.maps.gotoAndStop(r2)
      0414: r1.maps.players._visible = false
      042a: r1.maps.landmarks._visible = false
      0440: r1.maps.enemy._visible = false
      0451: r1.currentRot = 0.0
      045b: r1.bRotateMinimap = false
      046c: r1.customWaypointRot = 0.0
      0476: r1.customWaypointVisible = false
      0487: r1.currentObjectiveRot = 0.0
      0491: r1.currentObjectiveVisible = false
    }
    08f9: ?[?] = ?
    function (shouldRotate) {
      03f8: r1.bRotateMinimap = (r2 == 1)
      0403: if !!r1.bRotateMinimap goto off +58
      041e: r1.maps._rotation = 0.0
      042f: r1.currentRot = 0.0
      0441: r1.CancelOutIconRotation()
      0453: r1.UpdateNorthAlignedIcon()
      0469: r1.SetEdgeIconRotation(r1.waypointClip)
      047f: r1.SetEdgeIconRotation(r1.currentObjectiveClip)
    }
    09b1: ?[?] = ?
    function (x, y) {
      03f8: r1.maps._x = r3
      0408: r1.maps._y = r2
      0412: if !r1.bRotateMinimap goto off +101
      042d: r1.maps._rotation = 0.0
      0469: r1.rotateMap(r1.maps, (0.0 - r3), (0.0 - r2), r1.currentRot)
      047b: r1.CancelOutIconRotation()
    }
    0a5d: ?[?] = ?
    function () {
      03f5: r2 = 0.0
      040c: if !(r2 < r1.iconPathArray.length) goto off +51
      0433: r1.iconPathArray[r2]._rotation = (0.0 - r1.currentRot)
      043a: r2 = (r2 + 1)
      043f: goto off -74
      0450: r2 = 0.0
      0467: if !(r2 < r1.threatsArray.length) goto off +51
      048e: r1.threatsArray[r2]._rotation = (0.0 - r1.currentRot)
      0495: r2 = (r2 + 1)
      049a: goto off -74
    }
    0b26: ?[?] = ?
    function (rot) {
      03f8: r1.currentRot = (r2 % 360)
      040c: if !!(r1.currentRot < 360) goto off +27
      0426: r1.currentRot = (r1.currentRot - 360)
      0427: goto off +46
      0442: if !(r1.currentRot < 0.0) goto off +19
      0459: r1.currentRot = (360 + r1.currentRot)
      0463: if !r1.bRotateMinimap goto off +18
      0479: r1.UpdateNorthAlignedIcon()
      048f: r1.SetEdgeIconRotation(r1.waypointClip)
      04a5: r1.SetEdgeIconRotation(r1.currentObjectiveClip)
    }
    0bfb: ?[?] = ?
    function (edgeClip) {
      03f1: if !(r3 == undefined) goto off +5
      03fa: return undefined
      0447: r2 = (Math.atan2((r3._y - r1.playerClip._y), (r3._x - r1.playerClip._x)) * 57.29577951308232)
      0457: r2 = (r2 + 90)
      0465: if !r1.bRotateMinimap goto off +32
      0475: r2 = (r2 + r1.currentRot)
      0485: r2 = (r2 % 360)
      0497: if !!(r2 < 360) goto off +21
      04a7: r2 = (r2 - 360)
      04ac: goto off +37
      04c1: if !(r2 < 0.0) goto off +16
      04d1: r2 = (360 + r2)
      04e2: if !(r3 == r1.waypointClip) goto off +33
      04f0: r1.customWaypointRot = r2
      0502: r1.UpdateCustomWaypointAlignedIcon()
      0503: goto off +28
      0511: r1.currentObjectiveRot = r2
      0523: r1.UpdateCurrentObjectiveAlignedIcon()
    }
    0d53: ?[?] = ?
    function () {
      03f1: r3 = r1.customWaypointMC
      040b: r3.gotoAndStop(r1.customWaypointRot)
      0435: r2 = {'y': r1.waypointClip._y, 'x': r1.waypointClip._x}
      044f: r1.maps.localToGlobal(r2)
      045f: r1.globalToLocal(r2)
      0487: if (Math.abs(r2.y) > 90) goto off +35
      048c: (Math.abs(r2.y) > 90)
      04af: r1.customWaypointVisible = (Math.abs(r2.x) > 110)
      04bc: if r1.customWaypointVisible goto off +17
      04cd: goto off +8
      04da: '_alpha'[0.0] = 100
      04ed: if r1.customWaypointVisible goto off +13
      04fa: goto off +12
      050b: '_alpha'[100] = 0.0
    }
    0e89: ?[r3] = r1.waypointClip
    function () {
      03f1: r3 = r1.currentObjectiveMC
      040b: r3.gotoAndStop(r1.currentObjectiveRot)
      0435: r2 = {'y': r1.currentObjectiveClip._y, 'x': r1.currentObjectiveClip._x}
      044f: r1.maps.localToGlobal(r2)
      045f: r1.globalToLocal(r2)
      0487: if (Math.abs(r2.y) > 90) goto off +35
      048c: (Math.abs(r2.y) > 90)
      04af: r1.currentObjectiveVisible = (Math.abs(r2.x) > 110)
      04bc: if r1.currentObjectiveVisible goto off +17
      04cd: goto off +8
      04da: '_alpha'[0.0] = 100
      04ed: if r1.currentObjectiveVisible goto off +13
      04fa: goto off +12
      050b: '_alpha'[100] = 0.0
    }
    0fbf: ?[r3] = r1.currentObjectiveClip
    function () {
      03f1: r2 = r1.northMC
      040b: r2.gotoAndStop(r1.currentRot)
    }
    0ff5: ?[?] = ?
    function (mapClip, xPos, yPos, rot) {
      03fa: r3 = {'y': r4, 'x': r5}
      040e: r1.localToGlobal(r3)
      0424: r1._parent.globalToLocal(r3)
      042e: r1._rotation = r8
      0440: r2 = {'y': r4, 'x': r5}
      0454: r1.localToGlobal(r2)
      046a: r1._parent.globalToLocal(r2)
      0489: r1._x = (r1._x - (r2.x - r3.x))
      04a8: r1._y = (r1._y - (r2.y - r3.y))
    }
    10e2: ?[?] = ?
    function (scale) {
      03fe: r1.maps.themap._xscale = r2
      0414: r1.maps.themap._yscale = r2
    }
    1128: ?[?] = ?
    function () {
      0409: r3 = (r1.maps.getNextHighestDepth() - 1)
      041f: if !!(r3 < 0.0) goto off +97
      0439: r2 = r1.maps.getInstanceAtDepth(r3)
      0444: if !r2 goto off +18
      045a: r2.removeMovieClip()
      047b: r3 = (r1.maps.getNextHighestDepth() - 1)
      0480: goto off -119
      048e: <TargetPath >
      049e: r1.pathLen = (r1.length + 2)
      04c9: r1.threatsArray.splice(0.0, r1.threatsArray.length)
      04f4: r1.iconPathArray.splice(0.0, r1.iconPathArray.length)
    }
    1247: ?[?] = ?
    function (clip) {
      0405: <StringExtract >
      0406: eval(this.pathLen) = -1
      041d: var Obj = eval(((this + '.') + clip))
      042b: if !!(Obj == undefined) goto off +22
      0445: this.removeMovieClip()
    }
    12b9: ?.clip = clip
    function (threatString) {
      03f7: if !(r1.threatsArray == undefined) goto off +20
      040f: r1.threatsArray = new Array()
      041c: r2 = 0.0
      042d: r10 = 0.0
      043e: r9 = 0.0
      044f: r3 = 0.0
      0460: r4 = 0.0
      0474: r6 = new Array()
      0488: r6 = r11.split('|')
      049f: if !(r3 < r6.length) goto off +435
      04b3: if !(r6[r3] == '') goto off +5
      04b8: goto off +394
      04d0: if !!(r3 < r1.threatsArray.length) goto off +95
      04ec: r7 = r1.maps.getNextHighestDepth()
      0514: r8 = r1.maps.enemy.duplicateMovieClip(('enemy' + r2), r7)
      052e: r1.threatsArray.push(r8)
      0533: return undefined
      0549: r5 = r6[r3].split(',')
      055e: r2 = ToNumber(r5[0.0])
      056f: r10 = ToNumber(r5[1])
      0580: r9 = ToNumber(r5[2])
      05a4: if !(!r1.threatsArray[r2]._alpha < 100) goto off +25
      05c1: r1.threatsArray[r2]._alpha = 100
      05fe: r1.threatsArray[r2]._x = (r1.maps.themap._x + (r10 * r1.maps.themap._width))
      063b: r1.threatsArray[r2]._y = (r1.maps.themap._y + (r9 * r1.maps.themap._height))
      0642: r4 = (r4 + 1)
      064d: r3 = (r3 + 1)
      0652: goto off -452
      0669: if !(r4 < r1.threatsArray.length) goto off +74
      0686: if !(r4 < r1.threatsArray.length) goto off +45
      06a7: r1.threatsArray[r4]._alpha = 0.0
      06ae: r4 = (r4 + 1)
      06b3: goto off -68
    }
    15a9: ?[?] = ?
    15cd: ASSetPropFlags(_global.Minimap.prototype, null, 1)
