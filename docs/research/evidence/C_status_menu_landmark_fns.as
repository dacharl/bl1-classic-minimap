    function UpdateLandmark(clip, x, y, r) {
      0247: var Obj = eval(clip)
      0255: if !!(Obj == undefined) goto off +154
      029d: <SetProperty >
      02e1: <SetProperty >
      02f3: <SetProperty >
    }
    function AddLandmark(clip, x, y, r, frame) {
      025b: var NHD = map.maps.getNextHighestDepth()
      026b: var newClip = (frame + NHD)
      0275: var srcClip = eval(clip)
      0295: var newObject = srcClip.duplicateMovieClip(newClip, NHD)
      02ad: newObject.gotoAndStop(frame)
      02b6: <TargetPath >
      02b7: newClip = newObject
      02db: UpdateLandmark(newClip, x, y, r)
      02e2: return newClip
    }
    function SetMapScale(scale) {
      0257: map.maps.themap._xscale = r1
      0271: map.maps.themap._yscale = r1
