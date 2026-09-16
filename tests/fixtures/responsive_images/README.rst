Responsive image test fixtures
==============================

All fixtures in this directory are generated at test time with Pillow in
``pytest`` ``tmp_path``. No external downloads, no checked-in binaries.

Generation
----------

* ``tests/unit/test_responsive_images_quality.py`` builds every source image
  in memory (``Image.new`` + ``putdata``/``putpalette``/``putpixel``) and saves
  it to ``tmp_path`` with explicit ``format=`` and metadata arguments
  (``exif=``, ``comment=``, ``xmp=``, ``icc_profile=``, ``transparency=``,
  ``PngInfo`` text/iTXt).
* ``tests/fixtures/responsive_images/helpers.py`` provides ``make_request``,
  which sniffs the format from content and probes with
  ``PillowImageVariantGenerator``. Nothing here is read from disk outside
  ``tmp_path``.

Provenance
----------

* Colour blocks (240×120 red/blue), gradients, alpha checkerboards and CMYK
  patches are synthesised constants in the test module.
* The fixed sRGB ICC comes from LittleCMS at runtime:
  ``ImageCms.createProfile('sRGB')`` with the creation datetime frozen to
  ``(2000, 1, 1, 0, 0, 0)`` and the profile ID zeroed, so the same bytes come
  out across calls and processes.
* The “raw” sRGB ICC used as a palette source is the unfrozen
  ``createProfile('sRGB')`` output: colorimetrically sRGB but byte-different,
  which proves palette CMS relabels rather than byte-copies.
* Corrupt ICC fixtures are the literal bytes ``b"not-an-icc"`` with
  provenance recorded inline; Pillow embeds them verbatim for unchanged modes
  and LittleCMS rejects them when palette conversion must interpret them.

Oracle
------

* EXIF orientation uses the hardcoded 8-direction pixel table from task 3,
  independent of ``ImageOps.exif_transpose``.
* Resized alpha is compared against an independent oracle: the source alpha
  plane resized alone with ``Image.Resampling.LANCZOS`` (tolerance 1).
* Palette CMS colours are compared against a direct ``profileToProfile``
  call with ``Intent.RELATIVE_COLORIMETRIC`` and ``flags=0`` in the test.
* Metadata absence is verified on reopen (``getexif()``, ``info`` sentinels,
  ``text``) plus length-prefixed raw parsers: PNG chunk types and WebP RIFF
  tags walked along validated boundaries, so coincidental strings inside the
  ICC payload are never mistaken for metadata. WebP additionally asserts no
  ``EXIF`` tag exists even as an empty chunk.
* ``_inspect_variant`` enforces the same checks on every output file.

Quantization conditions
-----------------------

* 16-bit grayscale ``tRNS`` compares the pre-rounding 16-bit value and emits
  8-bit ``LA`` with lightness ``round(value / 257)`` and alpha 0/255. The
  test uses values 256/257 (both round to 1) to prove transparent and
  neighbouring pixels with identical lightness stay distinguishable by alpha.
* JPEG/WebP colour assertions sample interior block centres only, with per
  channel error ``<= 16`` in 8-bit. Lossless (PNG) alpha and gradient values
  must match exactly. Boundary compression noise is never a reason to drop
  an assertion.
