"""Dependency-free, Unicode PDF writer for tailored CVs.

The renderer embeds open-licensed TrueType fonts shipped with the package. Text remains
real/selectable text, with a ToUnicode map for ATS and PDF extractors. Latin uses Noto
Sans, Arabic uses Noto Sans Arabic, and CJK uses Droid Sans Fallback. Arabic is shaped
and displayed right-to-left; ActualText preserves the logical source string.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

PAGE_W, PAGE_H = 595.0, 842.0
MARGIN, BOTTOM = 54.0, 60.0
FONT_DIR = files("findmejob.render").joinpath("fonts")

# Arabic presentation forms: isolated, final, initial, medial. None means unavailable.
_ARABIC_FORMS = {
    "ا": (0xFE8D, 0xFE8E, None, None), "ب": (0xFE8F, 0xFE90, 0xFE91, 0xFE92),
    "ت": (0xFE95, 0xFE96, 0xFE97, 0xFE98), "ث": (0xFE99, 0xFE9A, 0xFE9B, 0xFE9C),
    "ج": (0xFE9D, 0xFE9E, 0xFE9F, 0xFEA0), "ح": (0xFEA1, 0xFEA2, 0xFEA3, 0xFEA4),
    "خ": (0xFEA5, 0xFEA6, 0xFEA7, 0xFEA8), "د": (0xFEA9, 0xFEAA, None, None),
    "ذ": (0xFEAB, 0xFEAC, None, None), "ر": (0xFEAD, 0xFEAE, None, None),
    "ز": (0xFEAF, 0xFEB0, None, None), "س": (0xFEB1, 0xFEB2, 0xFEB3, 0xFEB4),
    "ش": (0xFEB5, 0xFEB6, 0xFEB7, 0xFEB8), "ص": (0xFEB9, 0xFEBA, 0xFEBB, 0xFEBC),
    "ض": (0xFEBD, 0xFEBE, 0xFEBF, 0xFEC0), "ط": (0xFEC1, 0xFEC2, 0xFEC3, 0xFEC4),
    "ظ": (0xFEC5, 0xFEC6, 0xFEC7, 0xFEC8), "ع": (0xFEC9, 0xFECA, 0xFECB, 0xFECC),
    "غ": (0xFECD, 0xFECE, 0xFECF, 0xFED0), "ف": (0xFED1, 0xFED2, 0xFED3, 0xFED4),
    "ق": (0xFED5, 0xFED6, 0xFED7, 0xFED8), "ك": (0xFED9, 0xFEDA, 0xFEDB, 0xFEDC),
    "ل": (0xFEDD, 0xFEDE, 0xFEDF, 0xFEE0), "م": (0xFEE1, 0xFEE2, 0xFEE3, 0xFEE4),
    "ن": (0xFEE5, 0xFEE6, 0xFEE7, 0xFEE8), "ه": (0xFEE9, 0xFEEA, 0xFEEB, 0xFEEC),
    "و": (0xFEED, 0xFEEE, None, None), "ى": (0xFEEF, 0xFEF0, None, None),
    "ي": (0xFEF1, 0xFEF2, 0xFEF3, 0xFEF4), "ة": (0xFE93, 0xFE94, None, None),
    "ء": (0xFE80, None, None, None), "أ": (0xFE83, 0xFE84, None, None),
    "إ": (0xFE87, 0xFE88, None, None), "آ": (0xFE81, 0xFE82, None, None),
    "ؤ": (0xFE85, 0xFE86, None, None), "ئ": (0xFE89, 0xFE8A, 0xFE8B, 0xFE8C),
}

def _arabic(ch: str) -> bool: return "\u0600" <= ch <= "\u06ff"
def _joins_left(ch: str) -> bool: return ch in _ARABIC_FORMS and _ARABIC_FORMS[ch][2] is not None
def _joins_right(ch: str) -> bool: return ch in _ARABIC_FORMS and _ARABIC_FORMS[ch][1] is not None

def _shape_arabic(text: str) -> str:
    out=[]
    for i,ch in enumerate(text):
        forms=_ARABIC_FORMS.get(ch)
        if not forms: out.append(ch); continue
        prev=text[i-1] if i else ""; nxt=text[i+1] if i+1<len(text) else ""
        to_prev=_joins_left(prev) and _joins_right(ch)
        to_next=_joins_left(ch) and _joins_right(nxt)
        idx=3 if to_prev and to_next else 1 if to_prev else 2 if to_next else 0
        out.append(chr(forms[idx] or forms[0]))
    return "".join(reversed(out))

@dataclass
class _Font:
    filename: str
    data: bytes
    cmap: dict[int,int]
    widths: list[int]
    units: int
    bbox: tuple[int,int,int,int]
    ascent: int
    descent: int

    @classmethod
    def load(cls, filename: str):
        data=FONT_DIR.joinpath(filename).read_bytes()
        nt=struct.unpack_from(">H",data,4)[0]; tables={}
        for i in range(nt):
            tag,_,off,length=struct.unpack_from(">4sIII",data,12+i*16); tables[tag.decode()]=(off,length)
        head=tables["head"][0]; units=struct.unpack_from(">H",data,head+18)[0]
        bbox=struct.unpack_from(">hhhh",data,head+36)
        hhea=tables["hhea"][0]; ascent,descent=struct.unpack_from(">hh",data,hhea+4); nh=struct.unpack_from(">H",data,hhea+34)[0]
        maxp=tables["maxp"][0]; ng=struct.unpack_from(">H",data,maxp+4)[0]
        hmtx=tables["hmtx"][0]; widths=[]
        for i in range(nh): widths.append(struct.unpack_from(">H",data,hmtx+i*4)[0])
        widths += [widths[-1]]*(ng-len(widths))
        cmap=cls._cmap(data,tables["cmap"][0])
        return cls(filename,data,cmap,widths,units,bbox,ascent,descent)

    @staticmethod
    def _cmap(data,off):
        n=struct.unpack_from(">H",data,off+2)[0]; best=None
        for i in range(n):
            plat,enc,sub=struct.unpack_from(">HHI",data,off+4+i*8); pos=off+sub; fmt=struct.unpack_from(">H",data,pos)[0]
            rank={12:3,4:2}.get(fmt,0)+(1 if plat in (0,3) else 0)
            if not best or rank>best[0]: best=(rank,pos,fmt)
        _,p,fmt=best; out={}
        if fmt==12:
            groups=struct.unpack_from(">I",data,p+12)[0]
            for i in range(groups):
                start,end,gid=struct.unpack_from(">III",data,p+16+i*12)
                for cp in range(start,end+1): out[cp]=gid+cp-start
        elif fmt==4:
            seg=struct.unpack_from(">H",data,p+6)[0]//2; endp=p+14; startp=endp+2*seg+2; deltap=startp+2*seg; rangep=deltap+2*seg
            for i in range(seg):
                end=struct.unpack_from(">H",data,endp+2*i)[0]
                start=struct.unpack_from(">H",data,startp+2*i)[0]
                delta=struct.unpack_from(">h",data,deltap+2*i)[0]
                ro=struct.unpack_from(">H",data,rangep+2*i)[0]
                for cp in range(start,end+1):
                    if cp==0xffff: continue
                    if ro: gid=struct.unpack_from(">H",data,rangep+2*i+ro+2*(cp-start))[0]; gid=(gid+delta)&0xffff if gid else 0
                    else: gid=(cp+delta)&0xffff
                    if gid: out[cp]=gid
        return out

_FONTS: dict[str,_Font]={}
def _font(kind: str, bold=False):
    key=("cjk" if kind=="cjk" else "arabic" if kind=="arabic" else "latin")+("b" if bold else "")
    if key not in _FONTS:
        fn={"latin":"NotoSans-Regular.ttf","latinb":"NotoSans-Bold.ttf","arabic":"NotoSansArabic-Regular.ttf","arabicb":"NotoSansArabic-Bold.ttf","cjk":"DroidSansFallbackFull.ttf","cjkb":"DroidSansFallbackFull.ttf"}[key]
        _FONTS[key]=_Font.load(fn)
    return key,_FONTS[key]

def _kind(ch):
    if _arabic(ch): return "arabic"
    if ord(ch)>=0x2e80: return "cjk"
    return "latin"

def _runs(text):
    if not text: return []
    out=[]; start=0; kind=_kind(text[0])
    for i,ch in enumerate(text[1:],1):
        k=_kind(ch)
        if k!=kind: out.append((kind,text[start:i])); start=i; kind=k
    out.append((kind,text[start:])); return out

def _width(text,size,bold=False):
    total=0
    for kind,run in _runs(text):
        _,f=_font(kind,bold)
        total += sum(f.widths[f.cmap.get(ord(c),0)] for c in run)/f.units*size
    return total

def _wrap(text,size,max_w,bold=False):
    words=text.split()
    if not words:return [""]
    lines=[]; cur=words[0]
    for word in words[1:]:
        if _width(cur+" "+word,size,bold)<=max_w: cur += " "+word
        else: lines.append(cur); cur=word
    lines.append(cur); return lines

def _utf16hex(text): return (b"\xfe\xff"+text.encode("utf-16-be")).hex().upper()

class _Layout:
    def __init__(self): self.pages=[[]]; self.y=PAGE_H-MARGIN; self.used=set()
    @property
    def ops(self): return self.pages[-1]
    def _need(self,h):
        if self.y-h<BOTTOM:self.pages.append([]);self.y=PAGE_H-MARGIN
    def _show(self,text,size,bold,x,y,color=None):
        cursor=x
        for kind,run in _runs(text):
            key,f=_font(kind,bold); self.used.add(key)
            visual=_shape_arabic(run) if kind=="arabic" else run
            gids=[f.cmap.get(ord(c),0) for c in visual]
            glyphs="".join(f"{g:04X}" for g in gids)
            actual=f"/Span <</ActualText <{_utf16hex(run[::-1])}>>> BDC " if kind=="arabic" else ""
            close=" EMC" if kind=="arabic" else ""
            col=f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg " if color else ""
            self.ops.append(f"{col}{actual}BT /{key} {size} Tf {cursor:.1f} {y:.1f} Td <{glyphs}> Tj ET{close}")
            cursor += sum(f.widths[g] for g in gids)/f.units*size
    def text(self,text,size=10.5,bold=False,indent=0,after=4,leading=None,color=None):
        leading=leading or size*1.35; max_w=PAGE_W-MARGIN*2-indent
        for line in _wrap(text,size,max_w,bold): self._need(leading+after);self._show(line,size,bold,MARGIN+indent,self.y,color=color);self.y-=leading
        self.y-=after
    def heading(self,text,after=14.5):
        self._need(21+after);y=self.y;self._show(text,12.5,True,MARGIN,y);rule=y-7;self.ops.append(f"0.75 w {MARGIN:.1f} {rule:.1f} m {PAGE_W-MARGIN:.1f} {rule:.1f} l S");self.y=rule-after
    def bullet(self,text,size=10.5,after=2.5,color=None):
        lead=size*1.32
        for i,line in enumerate(_wrap(text,size,PAGE_W-MARGIN*2-14)):
            self._need(lead+after);self._show(("•  " if i==0 else "    ")+line,size,False,MARGIN,self.y,color=color);self.y-=lead
        self.y-=after
    def spacer(self,pts): self.y-=pts
    def rect(self,x,y,w,h,rgb):
        r,g,b=rgb
        self.ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg {x:.1f} {y:.1f} {w:.1f} {h:.1f} re f")
    def hline(self,y,rgb,width=1.0,x0=MARGIN,x1=PAGE_W-MARGIN):
        r,g,b=rgb
        self.ops.append(f"{r:.3f} {g:.3f} {b:.3f} RG {width} w {x0:.1f} {y:.1f} m {x1:.1f} {y:.1f} l S")
    def show_at(self,text,size,bold,x,y,color=None):
        self._show(text,size,bold,x,y,color=color)
    def section(self,title,color,rule_color):
        self._need(30); y=self.y
        self._show(title.upper(),11.5,True,MARGIN,y,color=color)
        rule=y-7; self.hline(rule,rule_color); self.y=rule-13
    def circle_image(self,name,cx,cy,r,iw,ih,ring=None):
        k=0.5522848
        scale=max(2*r/iw,2*r/ih); w,h=iw*scale,ih*scale
        x,y=cx-w/2,cy-h/2; c=k*r
        path=" ".join([
            f"{cx+r:.1f} {cy:.1f} m",
            f"{cx+r:.1f} {cy+c:.1f} {cx+c:.1f} {cy+r:.1f} {cx:.1f} {cy+r:.1f} c",
            f"{cx-c:.1f} {cy+r:.1f} {cx-r:.1f} {cy+c:.1f} {cx-r:.1f} {cy:.1f} c",
            f"{cx-r:.1f} {cy-c:.1f} {cx-c:.1f} {cy-r:.1f} {cx:.1f} {cy-r:.1f} c",
            f"{cx+c:.1f} {cy-r:.1f} {cx+r:.1f} {cy-c:.1f} {cx+r:.1f} {cy:.1f} c"])
        self.ops.append(f"q {path} W n {w:.1f} 0 0 {h:.1f} {x:.1f} {y:.1f} cm /{name} Do Q")
        if ring:
            rr,gg,bb=ring
            self.ops.append(f"q {rr:.3f} {gg:.3f} {bb:.3f} RG 2 w {path} S Q")

def _cmap_stream(mapping):
    pairs=[]
    for gid,cp in sorted(mapping.items()):
        enc=chr(cp).encode("utf-16-be").hex().upper(); pairs.append(f"<{gid:04X}> <{enc}>")
    chunks=[pairs[i:i+100] for i in range(0,len(pairs),100)]
    body="/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
    for c in chunks: body+=f"{len(c)} beginbfchar\n"+"\n".join(c)+"\nendbfchar\n"
    return (body+"endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend").encode()

def _build_pdf(pages,used,images=None):
    objs=[]
    def add(body=b""): objs.append(body.encode() if isinstance(body,str) else body);return len(objs)
    catalog=add(); pages_id=add(); font_ids={}
    embedded_by_file = {}
    for key in sorted(used):
        _,f=_font(key[:-1] if key.endswith('b') else key,key.endswith('b'))
        if f.filename in embedded_by_file:
            font_ids[key] = embedded_by_file[f.filename]
            continue
        ff=add(b"<< /Length "+str(len(f.data)).encode()+b" /Length1 "+str(len(f.data)).encode()+b" >>\nstream\n"+f.data+b"\nendstream")
        scale=lambda n:round(n*1000/f.units)
        desc=add(f"<< /Type /FontDescriptor /FontName /FMJ{key} /Flags 32 /FontBBox [{' '.join(str(scale(x)) for x in f.bbox)}] /ItalicAngle 0 /Ascent {scale(f.ascent)} /Descent {scale(f.descent)} /CapHeight {scale(f.ascent)} /StemV 80 /FontFile2 {ff} 0 R >>")
        used_gids={0}
        mapping={}
        for page in pages:
            for op in page:
                if f"/{key} " in op:
                    for hexs in __import__('re').findall(r"<([0-9A-F]+)> Tj",op): used_gids.update(int(hexs[i:i+4],16) for i in range(0,len(hexs),4))
        for cp,gid in f.cmap.items():
            if gid in used_gids and gid not in mapping: mapping[gid]=cp
        widths=" ".join(f"{gid} [{scale(f.widths[gid])}]" for gid in sorted(used_gids))
        cid=add(f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /FMJ{key} /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /FontDescriptor {desc} 0 R /CIDToGIDMap /Identity /W [{widths}] >>")
        cm=_cmap_stream(mapping); cmid=add(b"<< /Length "+str(len(cm)).encode()+b" >>\nstream\n"+cm+b"\nendstream")
        font_ids[key]=add(f"<< /Type /Font /Subtype /Type0 /BaseFont /FMJ{key} /Encoding /Identity-H /DescendantFonts [{cid} 0 R] /ToUnicode {cmid} 0 R >>")
        embedded_by_file[f.filename] = font_ids[key]
    img_ids={}
    for name,(data,w,h) in (images or {}).items():
        head=f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(data)} >>\nstream\n".encode()
        img_ids[name]=add(head+data+b"\nendstream")
    xobjects=" ".join(f"/{k} {v} 0 R" for k,v in img_ids.items())
    kids=[]
    resources=" ".join(f"/{k} {v} 0 R" for k,v in font_ids.items())
    for ops in pages:
        stream=("\n".join(ops)+"\n").encode(); content=add(b"<< /Length "+str(len(stream)).encode()+b" >>\nstream\n"+stream+b"endstream")
        res=f"/Font << {resources} >>"+(f" /XObject << {xobjects} >>" if xobjects else "")
        kids.append(add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {PAGE_W:.0f} {PAGE_H:.0f}] /Resources << {res} >> /Contents {content} 0 R >>"))
    objs[pages_id-1]=f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()
    objs[catalog-1]=f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
    out=bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"); offsets=[0]
    for i,b in enumerate(objs,1): offsets.append(len(out));out+=f"{i} 0 obj\n".encode()+b+b"\nendobj\n"
    xp=len(out);out+=f"xref\n0 {len(objs)+1}\n".encode()+b"0000000000 65535 f \n"+b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets[1:]);out+=f"trailer\n<< /Size {len(objs)+1} /Root {catalog} 0 R >>\nstartxref\n{xp}\n%%EOF\n".encode();return bytes(out)

def render_profile_pdf(lines_plan,out_path):
    lay=_Layout()
    for kind,text in lines_plan:
        if kind=="name":lay.text(text,20,True,after=2)
        elif kind=="contact":lay.text(text,9.5,after=2)
        elif kind=="heading":lay.spacer(4);lay.heading(text)
        elif kind=="subhead":lay.text(text,11,True,after=1.5)
        elif kind=="body":lay.text(text,10.5,after=3.5)
        elif kind=="bullet":lay.bullet(text)
        elif kind=="spacer":lay.spacer(6)
    path=Path(out_path);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(_build_pdf(lay.pages,lay.used));return path

def jpeg_size(data):
    """Return (width, height) of a JPEG image, or raise ValueError."""
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack_from(">HH", data, i + 5)
            return w, h
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = struct.unpack_from(">H", data, i + 2)[0]
        i += 2 + seg
    raise ValueError("no JPEG size marker found")


DEFAULT_THEME = {
    "navy": (0.122, 0.165, 0.267),   # deep navy header band
    "gold": (0.788, 0.635, 0.153),   # gold accents
    "paper": (1.0, 1.0, 1.0),
    "ink": (0.16, 0.16, 0.16),
}


def _render_designed(profile, job, out_path, photo=None, theme=None):
    """Designed theme: navy band with the name and contact block, gold section
    headings, navy role lines. Optional circular JPEG photo in the band.
    Text stays real and selectable, so the output remains ATS-safe."""
    from ..tailor import rank_bullets, rank_skills
    th = dict(DEFAULT_THEME)
    if theme:
        th.update(theme)
    lay = _Layout()
    images = {}
    photo_r = 40.0
    text_w = PAGE_W - MARGIN * 2
    if photo is not None:
        text_w -= photo_r * 2 + 16
    name_lines = _wrap(profile.full_name or "Curriculum Vitae", 20, text_w, bold=True)
    head_lines = _wrap(profile.headline, 11.5, text_w, bold=True) if profile.headline else []
    contact = "  |  ".join(p for p in [profile.email, profile.phone] if p)
    contact_lines = _wrap(contact, 9, text_w) if contact else []
    link_lines = _wrap("  |  ".join(f"{k}: {v}" for k, v in profile.links.items()), 9, text_w) if profile.links else []
    band_h = max(104.0, 30 + 24 * len(name_lines) + 14 * len(head_lines)
                 + 11.5 * (len(contact_lines) + len(link_lines)) + 22)
    lay.rect(0, PAGE_H - band_h, PAGE_W, band_h, th["navy"])
    lay.rect(0, PAGE_H - band_h - 3, PAGE_W, 3, th["gold"])
    if photo is not None:
        data = Path(photo).read_bytes()
        w, h = jpeg_size(data)
        images["ImPhoto"] = (data, w, h)
        lay.circle_image("ImPhoto", PAGE_W - MARGIN - photo_r, PAGE_H - band_h / 2,
                         photo_r, w, h, ring=th["gold"])
    y = PAGE_H - 40
    for line in name_lines:
        lay.show_at(line, 20, True, MARGIN, y, color=th["paper"]); y -= 24
    y -= 2
    for line in head_lines:
        lay.show_at(line, 11.5, True, MARGIN, y, color=th["gold"]); y -= 14
    y -= 4
    for line in contact_lines + link_lines:
        lay.show_at(line, 9, False, MARGIN, y, color=th["paper"]); y -= 11.5
    lay.y = PAGE_H - band_h - 26
    if profile.summary:
        lay.section("Summary", th["gold"], th["gold"]); lay.text(profile.summary, 10.5, after=3.5, color=th["ink"])
    skills = rank_skills(profile, job)
    if skills:
        lay.section("Skills", th["gold"], th["gold"]); lay.text("  •  ".join(skills), 10.5, after=3.5, color=th["ink"])
    if profile.experiences:
        lay.section("Experience", th["gold"], th["gold"])
        for exp in profile.experiences:
            dates = " - ".join(p for p in [exp.start, exp.end] if p)
            lay.text(f"{exp.role} - {exp.company}" + (f"   ({dates})" if dates else ""), 11, True, after=1.5, color=th["navy"])
            for b in rank_bullets(exp.bullets, job):
                lay.bullet(b, color=th["ink"])
            lay.spacer(6)
    if profile.education:
        lay.section("Education", th["gold"], th["gold"])
        for edu in profile.education:
            lay.text(f"{edu.degree} - {edu.school}" + (f"   ({edu.year})" if edu.year else ""), 11, True, after=1.5, color=th["navy"])
    path = Path(out_path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_build_pdf(lay.pages, lay.used, images))
    return path


def render_cv_pdf(profile, job, out_path, *, style="classic", photo=None, theme=None):
    """Render a tailored CV PDF. style="classic" is the plain single-column
    layout; style="designed" is the navy/gold band layout with an optional
    JPEG photo. job may be None for a general, untargeted CV."""
    if style == "designed":
        return _render_designed(profile, job, out_path, photo=photo, theme=theme)
    if style != "classic":
        raise ValueError(f"unknown CV style: {style!r}")
    from ..tailor import rank_bullets,rank_skills
    plan=[("name",profile.full_name or "Curriculum Vitae")]
    contact="  |  ".join(p for p in [profile.email,profile.phone] if p)
    if contact:plan.append(("contact",contact))
    if profile.links:plan.append(("contact","  |  ".join(f"{k}: {v}" for k,v in profile.links.items())))
    if profile.headline:plan.append(("body",profile.headline))
    if profile.summary:plan += [("heading","Summary"),("body",profile.summary)]
    skills=rank_skills(profile,job)
    if skills:plan += [("heading","Skills"),("body","  •  ".join(skills))]
    if profile.experiences:
        plan.append(("heading","Experience"))
        for exp in profile.experiences:
            dates=" - ".join(p for p in [exp.start,exp.end] if p);plan.append(("subhead",f"{exp.role} - {exp.company}"+(f"   ({dates})" if dates else "")))
            plan += [("bullet",b) for b in rank_bullets(exp.bullets,job)];plan.append(("spacer",""))
    if profile.education:
        plan.append(("heading","Education"))
        for edu in profile.education:plan.append(("subhead",f"{edu.degree} - {edu.school}"+(f"   ({edu.year})" if edu.year else "")))
    return render_profile_pdf(plan,out_path)
