fetch("https://example.com/steal").catch(function(){});
function loop(){ requestAnimationFrame(loop); }
requestAnimationFrame(loop);
