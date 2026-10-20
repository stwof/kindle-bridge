# -*- coding: utf-8 -*-
"""造几份不同「病症」的 EPUB，用来验证体检与修复逻辑。"""
import os, sys, zipfile

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/epubtest"
os.makedirs(OUT, exist_ok=True)

CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

def opf(title="测试书", author="某作者", lang="zh-CN", version="2.0",
        extra_meta="", extra_manifest="", extra_spine=""):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="{version}" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:language>{lang}</dc:language>
    <dc:identifier id="bookid">urn:uuid:12345678-1234-1234-1234-123456789abc</dc:identifier>
    <meta name="cover" content="coverimg"/>
    {extra_meta}
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="coverimg" href="images/cover.jpg" media-type="image/jpeg"/>
    <item id="css" href="style.css" media-type="text/css"/>
    <item id="c1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="chap2.xhtml" media-type="application/xhtml+xml"/>
    {extra_manifest}
  </manifest>
  <spine toc="ncx">
    <itemref idref="c1"/><itemref idref="c2"/>
    {extra_spine}
  </spine>
</package>"""

NCX = """<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head/><docTitle><text>测试书</text></docTitle>
  <navMap><navPoint id="n1" playOrder="1"><navLabel><text>第一章</text></navLabel>
  <content src="chap1.xhtml"/></navPoint></navMap></ncx>"""

CHAP = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{t}</title>
<link rel="stylesheet" href="style.css"/></head>
<body><h1>{t}</h1><p>这是第 {n} 章的正文，用来占位。</p></body></html>"""

CSS = "body { font-family: serif; line-height: 1.6; }"
JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffdb004300ffd9")

def base_files(**kw):
    return [
        ("META-INF/container.xml", CONTAINER.encode()),
        ("OEBPS/content.opf", opf(**kw).encode()),
        ("OEBPS/toc.ncx", NCX.encode()),
        ("OEBPS/style.css", CSS.encode()),
        ("OEBPS/chap1.xhtml", CHAP.format(t="第一章", n=1).encode()),
        ("OEBPS/chap2.xhtml", CHAP.format(t="第二章", n=2).encode()),
        ("OEBPS/images/cover.jpg", JPEG),
    ]

def write(name, files, mimetype_stored_first=True, mimetype_value=b"application/epub+zip",
          extra=None, compress_mimetype=False, mimetype_late=False):
    path = os.path.join(OUT, name)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        if mimetype_stored_first:
            zi = zipfile.ZipInfo("mimetype", (1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED if compress_mimetype else zipfile.ZIP_STORED
            z.writestr(zi, mimetype_value)
        for n, b in files:
            z.writestr(n, b)
        for n, b in (extra or []):
            z.writestr(n, b)
        if mimetype_late:      # mimetype 存在，但排在最后、且被压缩
            z.writestr("mimetype", mimetype_value)
    return path

made = []

# 1) 完全合规
made.append(write("01-规范.epub", base_files()))

# 2) mimetype 存在但排在最后且被压缩 + 夹带 macOS 垃圾
made.append(write("02-结构违规.epub", base_files(), mimetype_stored_first=False,
                  mimetype_late=True,
                  extra=[("__MACOSX/._x", b"junk"), ("OEBPS/.DS_Store", b"\x00\x01")]))

# 3) 正文被 DRM 加密（伪造）
ENC = b"""<?xml version="1.0" encoding="UTF-8"?>
<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
            xmlns:enc="http://www.w3.org/2001/04/xmlenc#">
  <enc:EncryptedData><enc:EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#aes128-cbc"/>
  <enc:CipherData><enc:CipherReference URI="OEBPS/content.opf"/></enc:CipherData>
  </enc:EncryptedData></encryption>"""
made.append(write("03-带DRM.epub", base_files(), extra=[("META-INF/encryption.xml", ENC)]))

# 4) 只有字体混淆（正常现象，不应判为 DRM）
ENCF = b"""<?xml version="1.0" encoding="UTF-8"?>
<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
            xmlns:enc="http://www.w3.org/2001/04/xmlenc#">
  <enc:EncryptedData><enc:EncryptionMethod Algorithm="http://www.idpf.org/2008/embedding"/>
  <enc:CipherData><enc:CipherReference URI="OEBPS/fonts/body.otf"/></enc:CipherData>
  </enc:EncryptedData></encryption>"""
made.append(write("04-字体混淆.epub", base_files(), extra=[("META-INF/encryption.xml", ENCF)]))

# 5) manifest 点名了包里没有的文件
made.append(write("05-缺资源.epub", base_files(
    extra_manifest='<item id="c3" href="chap3.xhtml" media-type="application/xhtml+xml"/>',
    extra_spine='<itemref idref="c3"/>')))

# 6) 固定版式 + 无封面 + 无语言
made.append(write("06-固定版式.epub", base_files(
    lang="", extra_meta='<meta property="rendition:layout">pre-paginated</meta>')))

# 7) 非 EPUB 垃圾文件
p = os.path.join(OUT, "07-不是zip.epub")
open(p, "wb").write(b"this is definitely not a zip file")
made.append(p)

# 8) 缺 container.xml
made.append(write("08-缺container.epub",
                  [f for f in base_files() if "container.xml" not in f[0]]))

print("已生成:")
for m in made:
    print(f"  {os.path.getsize(m):>8}  {os.path.basename(m)}")
