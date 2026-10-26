// Native canvas cropping; saved output uses the existing branding upload endpoint.
window.UnitBrandCrop = {
  create(kind, preview, changed, report) {
    const width = kind === 'icon' ? 512 : 1600;
    let height = kind === 'icon' ? 512 : 320;
    const region = document.createElement('div');
    region.className = `unit-brand-crop ${kind}`;
    region.hidden = true;
    region.innerHTML = `<canvas width="${width}" height="${height}" tabindex="0" role="img" aria-label="${kind === 'icon' ? 'Icon' : 'Banner'} crop preview. Drag or use arrow keys to reposition."></canvas><div class="brand-crop-controls"><label>Zoom<input type="range" min="1" max="4" step="0.01" value="1" aria-label="${kind} zoom"></label><button type="button">Reset crop</button></div><small>Drag the image to position it. Arrow keys also move it; hold Shift for larger steps.</small>`;
    // File controls already have a label; keep crop buttons and slider outside it.
    const field = preview.closest('label'),
      wrapper = document.createElement('div');
    wrapper.className = 'brand-image-editor';
    field.before(wrapper);
    wrapper.append(field, region);
    preview.hidden = true;
    const canvas = region.querySelector('canvas'),
      slider = region.querySelector('input'),
      reset = region.querySelector('button');
    const ctx = canvas.getContext('2d');
    let image = null,
      zoom = 1,
      x = 0,
      y = 0,
      generation = 0,
      dirty = false,
      loading = false,
      invalid = false,
      drag = null;
    function draw() {
      if (!image) return;
      const scale =
        Math.max(width / image.naturalWidth, height / image.naturalHeight) *
        zoom;
      const w = image.naturalWidth * scale,
        h = image.naturalHeight * scale;
      x = Math.max(-(w - width) / 2, Math.min((w - width) / 2, x));
      y = Math.max(-(h - height) / 2, Math.min((h - height) / 2, y));
      ctx.clearRect(0, 0, width, height);
      ctx.drawImage(image, (width - w) / 2 + x, (height - h) / 2 + y, w, h);
    }
    function mark() {
      dirty = true;
      changed();
    }
    slider.oninput = () => {
      if (!image || loading) return;
      const next = Number(slider.value);
      x *= next / zoom;
      y *= next / zoom;
      zoom = next;
      draw();
      mark();
    };
    reset.onclick = () => {
      if (!image || loading) return;
      zoom = 1;
      x = 0;
      y = 0;
      slider.value = '1';
      draw();
      mark();
    };
    canvas.onpointerdown = (event) => {
      if (
        !image ||
        loading ||
        (event.pointerType === 'mouse' && event.button !== 0)
      )
        return;
      event.preventDefault();
      canvas.focus();
      canvas.setPointerCapture(event.pointerId);
      drag = { id: event.pointerId, x: event.clientX, y: event.clientY };
    };
    canvas.onpointermove = (event) => {
      if (!drag || drag.id !== event.pointerId || !image) return;
      const bounds = canvas.getBoundingClientRect();
      x += ((event.clientX - drag.x) * width) / bounds.width;
      y += ((event.clientY - drag.y) * height) / bounds.height;
      drag.x = event.clientX;
      drag.y = event.clientY;
      draw();
      mark();
    };
    canvas.onpointerup =
      canvas.onpointercancel =
      canvas.onlostpointercapture =
        () => {
          drag = null;
        };
    canvas.onkeydown = (event) => {
      if (
        !image ||
        loading ||
        !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)
      )
        return;
      event.preventDefault();
      const step = event.shiftKey ? 40 : 10;
      if (event.key === 'ArrowLeft') x -= step;
      if (event.key === 'ArrowRight') x += step;
      if (event.key === 'ArrowUp') y -= step;
      if (event.key === 'ArrowDown') y += step;
      draw();
      mark();
    };
    function clear() {
      generation++;
      image = null;
      loading = false;
      invalid = false;
      dirty = false;
      drag = null;
      region.hidden = true;
      ctx.clearRect(0, 0, width, height);
    }
    return {
      clear,
      busy: () => loading && dirty,
      async set(source, replacement = false) {
        clear();
        dirty = replacement;
        const request = generation;
        loading = true;
        slider.disabled = reset.disabled = true;
        const next = new Image();
        try {
          await new Promise((resolve, reject) => {
            next.onload = resolve;
            next.onerror = () =>
              reject(
                new Error(
                  'Could not open this image. Choose another image or reset changes.',
                ),
              );
            next.src = source;
          });
          if (request !== generation) return;
          if (next.naturalWidth * next.naturalHeight > 40000000)
            throw new Error('Choose an image smaller than 40 megapixels.');
          if (kind === 'banner') {
            const bounds = document
              .getElementById('unit-brand-header')
              .getBoundingClientRect();
            height = Math.round(
              (width * Math.max(180, bounds.height)) /
                Math.max(320, bounds.width),
            );
            canvas.height = height;
          }
          image = next;
          zoom = 1;
          x = 0;
          y = 0;
          slider.value = '1';
          region.hidden = false;
          draw();
          dirty = replacement;
          if (replacement) changed();
        } catch (error) {
          if (request === generation) {
            invalid = replacement;
            report(error.message);
          }
        } finally {
          if (request === generation) {
            loading = false;
            slider.disabled = reset.disabled = false;
          }
        }
      },
      async append(data) {
        if (!dirty) return;
        if (loading)
          throw new Error('Wait for the branding preview to finish loading.');
        if (invalid)
          throw new Error(
            'Choose another image or reset changes before saving.',
          );
        if (!image) throw new Error('Choose an image before saving.');
        const blob = await new Promise((resolve) =>
          canvas.toBlob(resolve, 'image/png'),
        );
        if (!blob || blob.size > 4 * 1024 * 1024)
          throw new Error(
            'The cropped image could not be prepared. Choose another image.',
          );
        data.set(kind, blob, `${kind}.png`);
      },
    };
  },
};
