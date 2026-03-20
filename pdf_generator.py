"""
PDF Generator for iSoftrend System — v5
Fixes: header strip overlap, phone+email newline bug, stamp visible, bigger sign+stamp, thank you msg
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os, qrcode
from qrcode.constants import ERROR_CORRECT_M
from datetime import datetime
from urllib.parse import quote

_FONTS_OK = False
def _register_fonts():
    global _FONTS_OK
    if _FONTS_OK: return
    for n, b in [
        ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
        ('C:/Windows/Fonts/arial.ttf',   'C:/Windows/Fonts/arialbd.ttf'),
        ('C:/Windows/Fonts/calibri.ttf', 'C:/Windows/Fonts/calibrib.ttf'),
    ]:
        try:
            if os.path.exists(n) and os.path.exists(b):
                pdfmetrics.registerFont(TTFont('DV', n))
                pdfmetrics.registerFont(TTFont('DVB', b))
                _FONTS_OK = True; return
        except: continue

def F():  return 'DV'  if _FONTS_OK else 'Helvetica'
def FB(): return 'DVB' if _FONTS_OK else 'Helvetica-Bold'

BLACK = colors.HexColor('#000000')
RED   = colors.HexColor('#CC0000')

def fmt_date(s):
    if not s: return ''
    try:    return datetime.strptime(s,'%Y-%m-%d').strftime('%d/%m/%Y')
    except: return s

def payment_status_label(key):
    return {'unpaid':'Unpaid','partial':'Partially Paid','paid':'Paid'}.get(
        (key or '').strip(), 'Unpaid')

def payment_terms_label(key):
    return {'due_on_receipt':'Due on Receipt','net_15':'Net 15 Days',
            'net_30':'Net 30 Days','net_60':'Net 60 Days'}.get(
        (key or '').strip(), 'Due on Receipt')

def _n2w(n):
    ones=['','One','Two','Three','Four','Five','Six','Seven','Eight','Nine','Ten',
          'Eleven','Twelve','Thirteen','Fourteen','Fifteen','Sixteen','Seventeen',
          'Eighteen','Nineteen']
    tens=['','','Twenty','Thirty','Forty','Fifty','Sixty','Seventy','Eighty','Ninety']
    if n==0: return 'Zero'
    if n<0:  return 'Minus '+_n2w(-n)
    p=[]
    if n>=10000000: p.append(_n2w(n//10000000)+' Crore'); n%=10000000
    if n>=100000:   p.append(_n2w(n//100000)+' Lakh');    n%=100000
    if n>=1000:     p.append(_n2w(n//1000)+' Thousand');  n%=1000
    if n>=100:      p.append(ones[n//100]+' Hundred');    n%=100
    if n>=20:
        w=tens[n//10]; w+=(' '+ones[n%10]) if n%10 else ''; p.append(w)
    elif n>0: p.append(ones[n])
    return ' '.join(p)

def amount_in_words(amount):
    try:
        r=int(amount); p=round((amount-r)*100)
        w=_n2w(r)
        if p: w+=f' And {_n2w(p)} Paise'
        return f'INR {w} rupees only'
    except: return f'INR {amount}'

def _first(paths):
    return next((p for p in paths if p and os.path.exists(p)), None)

def _logo(s):
    u=s.get('logo','').strip()
    return _first([f'static/uploads/{u}' if u else None,
                   'static/img/logo.png','static/uploads/main.png'])

def _watermark(s):
    w=s.get('watermark','').strip()
    return _first([f'static/uploads/{w}' if w else None,
                   f'static/img/{w}'     if w else None,
                   'static/img/water.jpeg','static/img/watermark.png'])

def _qr_img(s):
    q=s.get('qr_code','')
    return _first([f'static/uploads/{q}' if q else None,
                   f'static/img/{q}'     if q else None,
                   'static/img/qr.png','static/uploads/qr.png'])

def _signature(s):
    sf=s.get('signature','').strip()
    return _first([f'static/uploads/signatures/{sf}' if sf else None,
                   f'static/uploads/{sf}'            if sf else None,
                   'static/uploads/signatures/default_sign.png',
                   'static/img/default_sign.png','static/uploads/default_sign.png'])

def _stamp(s):
    return _first(['static/img/stamp.png','static/uploads/stamp.png'])

def _box(c,x,y,w,h,lw=0.6):
    c.setStrokeColor(BLACK); c.setLineWidth(lw); c.rect(x,y,w,h,stroke=1,fill=0)
def _hl(c,x1,x2,y,lw=0.6):
    c.setStrokeColor(BLACK); c.setLineWidth(lw); c.line(x1,y,x2,y)
def _vl(c,x,y1,y2,lw=0.6):
    c.setStrokeColor(BLACK); c.setLineWidth(lw); c.line(x,y1,x,y2)

def _wrap(text,font,size,max_w,cv):
    words=str(text).split(); lines,line=[],''
    for w in words:
        t=(line+' '+w).strip()
        if cv.stringWidth(t,font,size)<=max_w: line=t
        else:
            if line: lines.append(line)
            line=w
    if line: lines.append(line)
    return lines or ['']

def _wrap_ml(text,font,size,max_w,cv):
    lines=[]
    for para in str(text or '').splitlines() or ['']:
        lines.extend(_wrap(para,font,size,max_w,cv))
    return lines or ['']

def _draw_wm(cv,settings,pw,ph):
    path=_watermark(settings)
    if not path: return
    try:
        from PIL import Image as PI, ImageOps
        os.makedirs('static/pdfs',exist_ok=True); tmp='static/pdfs/_wm.png'
        with PI.open(path) as src:
            img=ImageOps.exif_transpose(src).convert('RGBA')
            alpha=img.split()[3].point(lambda a:int(a*0.07))
            img.putalpha(alpha); iw,ih=img.size; img.save(tmp,'PNG')
        scale=(pw*0.80)/iw; dw,dh=iw*scale,ih*scale
        cv.drawImage(tmp,(pw-dw)/2,(ph-dh)/2+10*mm,
                     width=dw,height=dh,preserveAspectRatio=True,mask='auto')
        try: os.remove(tmp)
        except: pass
    except Exception as e: print(f'[WM]{e}')

def _draw_logo(cv,settings,x,top_y,max_w,max_h):
    path=_logo(settings)
    if not path: return
    try:
        from PIL import Image as PI, ImageOps
        with PI.open(path) as src:
            img=ImageOps.exif_transpose(src); iw,ih=img.size
        ratio=min(1.0,min(max_w/iw,max_h/ih))
        cv.drawImage(path,x,top_y-ih*ratio,width=iw*ratio,height=ih*ratio,
                     preserveAspectRatio=True,mask='auto')
    except Exception as e: print(f'[Logo]{e}')

def _draw_upi_qr(cv,payload,x,y,size):
    try:
        from PIL import Image as PI
        q=qrcode.QRCode(error_correction=ERROR_CORRECT_M,box_size=10,border=4)
        q.add_data(payload); q.make(fit=True)
        img=q.make_image(fill_color='black',back_color='white').convert('RGB')
        img=img.resize((600,600),PI.NEAREST)
        os.makedirs('static/pdfs',exist_ok=True); tmp='static/pdfs/_uqr.png'
        img.save(tmp,'PNG'); pad=1*mm
        cv.setFillColor(colors.white)
        cv.rect(x-pad,y-pad,size+2*pad,size+2*pad,stroke=0,fill=1)
        cv.drawImage(tmp,x,y,width=size,height=size,
                     preserveAspectRatio=True,mask='auto')
        try: os.remove(tmp)
        except: pass
        return True
    except: return False

def _draw_img_qr(cv,path,x,y,size):
    try:
        from PIL import Image as PI
        os.makedirs('static/pdfs',exist_ok=True); tmp='static/pdfs/_iqr.png'
        with PI.open(path) as img:
            img.convert('L').point(lambda p:0 if p<160 else 255,'1')\
               .resize((600,600),PI.NEAREST).save(tmp,'PNG')
        cv.drawImage(tmp,x,y,width=size,height=size,
                     preserveAspectRatio=True,mask='auto')
        try: os.remove(tmp)
        except: pass
        return True
    except: return False

def _rr(cv,rx,ry,s,size=9,bold=True):
    cv.setFont(FB() if bold else F(),size)
    cv.drawRightString(rx,ry,f'\u20b9{s}')

# ═══════════════════════════════════════════════════════════════════════════════
def generate_pdf(doc,customer,settings,doc_type):
    _register_fonts()
    os.makedirs('static/pdfs',exist_ok=True)
    out=f"static/pdfs/{doc.get('number','doc')}.pdf"
    pw,ph=A4
    cv=canvas.Canvas(out,pagesize=A4)
    cv.setTitle(f"{doc.get('number','')} - {settings.get('company_name','')}")
    _draw_page(cv,doc,customer,settings,doc_type,pw,ph)
    cv.save()
    return out

def _draw_page(cv,doc,customer,settings,doc_type,pw,ph):
    f=F(); fb=FB()
    L=14*mm; W=pw-2*L   # 182mm usable
    y=ph-12*mm
    page_top=y

    _draw_wm(cv,settings,pw,ph)

    # ══════════════════════════════════════════════════════════════════════════
    # HEADER  —  TOP part (Logo+Company | INVOICE)
    #         —  BOTTOM STRIP (GSTIN+contact | Invoice#)
    # KEY FIX: vertical divider runs full HDR_H so strip is split correctly
    # ══════════════════════════════════════════════════════════════════════════
    META_W = W * 0.385
    COMP_W = W - META_W
    meta_x = L + COMP_W

    TOP_H   = 34*mm
    STRIP_H = 10*mm
    HDR_H   = TOP_H + STRIP_H  # 44mm total

    # Outer box
    _box(cv, L, y-HDR_H, W, HDR_H, lw=1.5)
    # Vertical divider — FULL height (fixes overlap)
    _vl(cv, meta_x, y-HDR_H, y, lw=1.2)
    # Horizontal strip divider
    _hl(cv, L, L+W, y-TOP_H, lw=0.8)

    # Left top: Logo + company
    _draw_logo(cv, settings, L+3*mm, y-3*mm, 34*mm, 24*mm)
    tx = L+40*mm
    cv.setFont(fb,13); cv.setFillColor(BLACK)
    cv.drawString(tx, y-9*mm, settings.get('company_name','iSoftrend System'))
    cv.setFont(f,8.5)
    ay=y-15*mm
    for line in _wrap(settings.get('address',''), f, 8.5, COMP_W-42*mm, cv):
        cv.drawString(tx, ay, line); ay-=4.2*mm

    # Bottom strip — spans FULL width, split into 2 zones by meta_x:
    #   LEFT ZONE  (L → meta_x):  [GSTIN: xxx] | [phone I email I website]
    #   RIGHT ZONE (meta_x → R):  Invoice# INV-xxx
    strip_top = y - TOP_H
    cv.setFillColor(BLACK)
    phone   = settings.get('phone','').replace('+91','').strip()
    email   = settings.get('email','')
    website = settings.get('website','')
    gstin   = settings.get('gstin','')

    # -- LEFT ZONE: GSTIN divider then contact --
    SF = 7.5   # strip font size — small enough to fit everything in 10mm strip

    # Fixed split: GSTIN takes ~33% of left zone, contact takes the rest
    gstin_str   = f"GSTIN: {gstin}"
    divider_x   = L + COMP_W * 0.36   # divider at 36% of left zone width

    # Inner vertical divider (GSTIN | contact), only inside left zone
    _vl(cv, divider_x, y-HDR_H, y-TOP_H, lw=0.8)

    # GSTIN — left of inner divider
    cv.setFont(f, SF); cv.setFillColor(BLACK)
    cv.drawString(L+2*mm, strip_top - 4*mm, gstin_str)

    # Contact — right of inner divider, clipped to meta_x
    contact_str = f"+91 {phone} | {email} | {website}"
    cv.setFont(f, SF)
    # Shrink font until it fits
    fs = SF
    while fs >= 5.5 and cv.stringWidth(contact_str, f, fs) > (meta_x - divider_x - 5*mm):
        fs -= 0.25
    cv.setFont(f, fs)
    cv.drawString(divider_x + 3*mm, strip_top - 4*mm, contact_str)

    # -- RIGHT ZONE: Invoice# (meta_x → right edge) --
    cv.setFont(f, 9); cv.setFillColor(BLACK)
    cv.drawString(meta_x + 3*mm, strip_top - 4.5*mm, 'Invoice#')
    cv.setFont(fb, 11)
    cv.drawRightString(L+W-3*mm, strip_top - 4.5*mm, doc.get('number',''))

    # Right top: INVOICE big text (vertically centred in TOP_H)
    title_map={'quotation':'QUOTATION','proforma':'PROFORMA INVOICE','invoice':'INVOICE'}
    doc_title=title_map.get(doc_type,'INVOICE')
    cv.setFont(fb,34); cv.setFillColor(BLACK)
    title_w=cv.stringWidth(doc_title,fb,34)
    title_x=meta_x+(META_W-title_w)/2
    # Centre vertically in TOP_H
    cv.drawString(title_x, y-TOP_H/2-4*mm, doc_title)


    y -= HDR_H

    # ══════════════════════════════════════════════════════════════════════════
    # BILL TO (left) | Invoice meta (right)
    # ══════════════════════════════════════════════════════════════════════════
    BT_H = 38*mm
    _box(cv, L, y-BT_H, W, BT_H, lw=0.8)
    _vl(cv, meta_x, y-BT_H, y, lw=0.8)

    # Left: customer info
    cv.setFont(fb,8.5); cv.setFillColor(BLACK)
    cv.drawString(L+2*mm, y-4.5*mm, 'Bill To')
    cy=y-10*mm
    bname=(customer.get('company') or customer.get('name','')).upper()
    cv.setFont(fb,10); cv.drawString(L+2*mm, cy, bname); cy-=5*mm
    cv.setFont(f,8)
    addr_parts=[p for p in [customer.get('address',''),customer.get('city',''),
                              customer.get('state',''),customer.get('country','')] if p]
    for line in _wrap(', '.join(addr_parts), f, 8, COMP_W-4*mm, cv):
        cv.drawString(L+2*mm, cy, line); cy-=4.2*mm
    # FIX: phone and email on SEPARATE lines (no \n in drawString)
    ph_c=customer.get('phone',''); em_c=customer.get('email','')
    if ph_c:
        cv.drawString(L+2*mm, cy, f"+91 {ph_c}"); cy-=4.2*mm
    if em_c:
        cv.drawString(L+2*mm, cy, em_c); cy-=4.2*mm
    ws_c=customer.get('website','')
    if ws_c: cv.drawString(L+2*mm, cy, ws_c); cy-=4.2*mm
    gs_c=customer.get('gstin','')
    if gs_c: cv.drawString(L+2*mm, cy, f"GSTIN: {gs_c}")

    # Right: invoice dates (label left, value right-aligned)
    mlx=meta_x+3*mm; mrx=L+W-3*mm; my=y-8*mm
    for label,val in [
        ('Invoice Date', fmt_date(doc.get('date',''))),
        ('Terms',        payment_status_label(doc.get('payment_status',''))),
        ('Due Date',     fmt_date(doc.get('due_date',''))),
    ]:
        cv.setFont(f,9); cv.setFillColor(BLACK); cv.drawString(mlx,my,label)
        cv.setFont(fb,9); cv.drawRightString(mrx,my,val)
        my-=6*mm
    my-=2*mm
    cv.setFont(f,9); cv.setFillColor(BLACK); cv.drawString(mlx,my,'Place Of Supply')
    my-=5.5*mm
    cv.setFont(fb,9)
    cv.drawString(mlx,my,f"{settings.get('state','Gujarat')}({settings.get('state_code','24')})")

    y -= BT_H

    # ══════════════════════════════════════════════════════════════════════════
    # ITEMS TABLE
    # GST mode:     [8,53,13,17,17,9,14,9,14,28] = 182mm  (10 cols)
    # Non-GST mode: [8,63,16,20,20,55]           = 182mm  (6 cols)
    # ══════════════════════════════════════════════════════════════════════════
    items  = doc.get('items',[])
    gst_on = doc.get('gst_enabled', True)

    hS=ParagraphStyle('h',fontName=fb,fontSize=8.5,leading=10,alignment=TA_CENTER)
    iS=ParagraphStyle('i',fontName=f, fontSize=8,  leading=10,alignment=TA_LEFT)

    if gst_on:
        # ── GST table: 10 columns ────────────────────────────────────────────
        COL_W = [w*mm for w in [8,53,13,17,17,9,14,9,14,28]]
        hdr1  = [Paragraph(t,hS) for t in
                 ['#','Item & Description','Qty','Rate','Discount','CGST','','SGST','','Amount']]
        hdr2  = ['','','','','',
                 Paragraph('%',hS),Paragraph('Amt',hS),
                 Paragraph('%',hS),Paragraph('Amt',hS),'']
        rows  = [hdr1, hdr2]
        for idx,item in enumerate(items,1):
            np_=Paragraph(
                f"<b>{item.get('name','')}</b>"
                f"<br/><font size='7' color='#444444'>{item.get('description','')}</font>"
                f"<br/><font size='7'>HSN/SAC: {item.get('hsn_sac','')}</font>",iS)
            disc=item.get('discount',0) or 0
            rows.append([str(idx),np_,
                f"{float(item.get('qty',1)):.2f}",
                f"{float(item.get('rate',0)):,.2f}",
                f"{int(disc)}%",
                str(item.get('cgst_perc','9')),
                f"{float(item.get('cgst',0)):,.2f}",
                str(item.get('sgst_perc','9')),
                f"{float(item.get('sgst',0)):,.2f}",
                f"{float(item.get('amount',0)):,.2f}"])
        empty=['']*10
        while len(rows)<6: rows.append(empty)

        tbl=Table(rows,colWidths=COL_W,repeatRows=2)
        tbl.setStyle(TableStyle([
            ('FONTNAME',      (0,0),(-1,1), fb),
            ('FONTSIZE',      (0,0),(-1,1), 8.5),
            ('ALIGN',         (0,0),(-1,1), 'CENTER'),
            ('VALIGN',        (0,0),(-1,1), 'MIDDLE'),
            ('TOPPADDING',    (0,0),(-1,1), 3),
            ('BOTTOMPADDING', (0,0),(-1,1), 3),
            ('FONTNAME',      (0,2),(-1,-1), f),
            ('FONTSIZE',      (0,2),(-1,-1), 8.5),
            ('VALIGN',        (0,2),(-1,-1), 'TOP'),
            ('TOPPADDING',    (0,2),(-1,-1), 4),
            ('BOTTOMPADDING', (0,2),(-1,-1), 4),
            ('LEFTPADDING',   (0,0),(-1,-1), 2),
            ('RIGHTPADDING',  (0,0),(-1,-1), 2),
            ('ALIGN',(0,2),(0,-1),'CENTER'),
            ('ALIGN',(2,2),(4,-1),'CENTER'),
            ('ALIGN',(5,2),(9,-1),'CENTER'),
            ('GRID',    (0,0),(-1,-1),0.5,BLACK),
            ('BOX',     (0,0),(-1,-1),1.2,BLACK),
            ('LINEBELOW',(0,1),(-1,1),1.0,BLACK),
            ('SPAN',(5,0),(6,0)),('SPAN',(7,0),(8,0)),
        ]))

    else:
        # ── Non-GST table: 6 columns (no CGST/SGST) ─────────────────────────
        COL_W = [w*mm for w in [8,63,20,22,16,53]]   # = 182mm
        hdr1  = [Paragraph(t,hS) for t in
                 ['#','Item & Description','Qty','Rate','Discount','Amount']]
        rows  = [hdr1]
        for idx,item in enumerate(items,1):
            np_=Paragraph(
                f"<b>{item.get('name','')}</b>"
                f"<br/><font size='7' color='#444444'>{item.get('description','')}</font>"
                f"<br/><font size='7'>HSN/SAC: {item.get('hsn_sac','')}</font>",iS)
            disc=item.get('discount',0) or 0
            rows.append([str(idx),np_,
                f"{float(item.get('qty',1)):.2f}",
                f"{float(item.get('rate',0)):,.2f}",
                f"{int(disc)}%",
                f"{float(item.get('amount',0)):,.2f}"])
        empty=['']*6
        while len(rows)<6: rows.append(empty)

        tbl=Table(rows,colWidths=COL_W,repeatRows=1)
        tbl.setStyle(TableStyle([
            ('FONTNAME',      (0,0),(-1,0), fb),
            ('FONTSIZE',      (0,0),(-1,0), 8.5),
            ('ALIGN',         (0,0),(-1,0), 'CENTER'),
            ('VALIGN',        (0,0),(-1,0), 'MIDDLE'),
            ('TOPPADDING',    (0,0),(-1,0), 3),
            ('BOTTOMPADDING', (0,0),(-1,0), 3),
            ('FONTNAME',      (0,1),(-1,-1), f),
            ('FONTSIZE',      (0,1),(-1,-1), 8.5),
            ('VALIGN',        (0,1),(-1,-1), 'TOP'),
            ('TOPPADDING',    (0,1),(-1,-1), 4),
            ('BOTTOMPADDING', (0,1),(-1,-1), 4),
            ('LEFTPADDING',   (0,0),(-1,-1), 2),
            ('RIGHTPADDING',  (0,0),(-1,-1), 2),
            ('ALIGN',(0,1),(0,-1),'CENTER'),
            ('ALIGN',(2,1),(4,-1),'CENTER'),
            ('ALIGN',(5,1),(5,-1),'CENTER'),
            ('GRID',    (0,0),(-1,-1),0.5,BLACK),
            ('BOX',     (0,0),(-1,-1),1.2,BLACK),
            ('LINEBELOW',(0,0),(-1,0),1.0,BLACK),
        ]))

    # Reserve exact space for all sections below table
    BELOW = 8*mm+34*mm+42*mm+9*mm+24*mm+9*mm+14*mm  # TOT+SUM+FTR+NT+TRM+TY+margin
    avail_h = y - BELOW
    _,th=tbl.wrap(W,avail_h)
    if th<=avail_h:
        tbl.drawOn(cv,L,y-th); y-=th
    else:
        splits=tbl.split(W,avail_h)
        if splits:
            _,hh=splits[0].wrap(W,avail_h); splits[0].drawOn(cv,L,y-hh)
        cv.showPage(); _draw_wm(cv,settings,pw,ph)
        y=ph-15*mm
        rem=splits[1] if len(splits)>1 else tbl
        _,hh2=rem.wrap(W,y-86*mm); rem.drawOn(cv,L,y-hh2); y-=hh2

    # ══════════════════════════════════════════════════════════════════════════
    # TOTAL ROW
    # ══════════════════════════════════════════════════════════════════════════
    TOT_H=8*mm
    AMT_W=28*mm; TAX_W=22*mm; DESC_W=W-AMT_W-TAX_W
    total_v   =float(doc.get('total',0))
    total_tax =float(doc.get('total_tax',0))
    total_qty =sum(float(i.get('qty',0)) for i in items)
    total_disc=sum(float(i.get('rate',0))*float(i.get('qty',0))*
                   float(i.get('discount',0) or 0)/100 for i in items)

    _box(cv,L,          y-TOT_H,DESC_W,TOT_H)
    _box(cv,L+DESC_W,   y-TOT_H,TAX_W, TOT_H)
    _box(cv,L+DESC_W+TAX_W,y-TOT_H,AMT_W,TOT_H)

    cv.setFont(f,9); cv.setFillColor(BLACK)
    cv.drawString(L+2*mm,y-5.5*mm,'Total')
    cv.drawString(L+DESC_W/2,y-5.5*mm,f'{total_qty:,.0f}')
    cv.setFont(fb,9)
    disc_disp=total_disc if total_disc>0 else total_tax
    cv.drawRightString(L+DESC_W+TAX_W-2*mm,y-5.5*mm,f'\u20b9 {disc_disp:,.0f}')
    _rr(cv,L+W-2*mm,y-5.5*mm,f'{total_v:,.2f}',10)
    y-=TOT_H

    # ══════════════════════════════════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════════════════════════════════
    SUM_H=34*mm
    _box(cv,L,y-SUM_H,W,SUM_H,lw=0.8)
    cv.setFont(f,8); cv.setFillColor(BLACK)
    cv.drawString(L+2*mm,y-6*mm,'Total In Words')
    cv.setFont(fb,9)
    wl=_wrap(amount_in_words(total_v),fb,9,W*0.50,cv)
    wy=y-12*mm
    for line in wl: cv.drawString(L+2*mm,wy,line); wy-=5*mm

    rx=L+W-66*mm; rv=L+W-3*mm; ry=y-6*mm
    cgst_t=float(doc.get('cgst_total',0))
    sgst_t=float(doc.get('sgst_total',0))
    paid_v=float(doc.get('amount_paid',0))
    bal_v =float(doc.get('balance_due',0))
    # Only show CGST/SGST rows when GST is enabled
    summary_rows = []
    if gst_on:
        summary_rows += [
            ('CGST (9%)',   f'{cgst_t:,.2f}', BLACK,  9, False),
            ('SGST (9%)',   f'{sgst_t:,.2f}', BLACK,  9, False),
        ]
    summary_rows += [
        ('Total',        f'{total_v:,.2f}', BLACK, 10, True),
        ('Payment Made', f'{paid_v:,.2f}',  RED,    9, False),
        ('Balance Due',  f'{bal_v:,.2f}',   BLACK, 10, True),
    ]
    for lbl,val,vcol,vsz,lbold in summary_rows:
        cv.setFont(fb if lbold else f,9); cv.setFillColor(BLACK)
        cv.drawString(rx,ry,lbl)
        cv.setFont(fb,vsz); cv.setFillColor(vcol)
        cv.drawRightString(rv,ry,f'\u20b9{val}')
        ry-=6.5*mm
    cv.setFillColor(BLACK)
    y-=SUM_H

    # ══════════════════════════════════════════════════════════════════════════
    # FOOTER: one box, no inner dividers
    #   Left:   Bank details
    #   Centre: QR code
    #   Right:  FOR label + Stamp + Signature
    # ══════════════════════════════════════════════════════════════════════════
    FTR_H = 42*mm
    _box(cv, L, y-FTR_H, W, FTR_H, lw=0.8)

    # ── Bank details (left ~46%) ──────────────────────────────────────────────
    bx = L+2*mm; by = y-5.5*mm
    for lbl, key, dflt in [
        ('BANK NAME',      'bank_name',     'Kotak Mahindra Bank Ltd.'),
        ('ACCOUNT NUMBER', 'account_number','5949479030'),
        ('ACCOUNT NAME',   'account_name',  'ISOFTREND SYSTEM'),
        ('BRANCH',         'branch',        'ODHAV GJ, AHMEDABAD'),
        ('IFSC',           'ifsc',          'KKBK0002563'),
        ('UPI',            'upi',           '7984823208@kotak'),
    ]:
        cv.setFont(fb, 8); cv.setFillColor(BLACK)
        cv.drawString(bx, by, f'{lbl}:')
        lw2 = cv.stringWidth(f'{lbl}:', fb, 8)
        cv.setFont(f, 8)
        cv.drawString(bx+lw2+1*mm, by, settings.get(key, dflt))
        by -= 5.2*mm

    # ── QR code (centre, starts at 46% of width) ─────────────────────────────
    QSIZE = 26*mm
    qx    = L + W*0.46
    qy    = y - FTR_H + 6*mm
    upi   = settings.get('upi','').strip()
    qr_amt = float(doc.get('balance_due',0) or doc.get('total',0) or 0)
    if qr_amt <= 0: qr_amt = float(doc.get('total',0) or 0)
    if upi:
        payee   = quote(settings.get('account_name', settings.get('company_name','iSoftrend System')))
        payload = f"upi://pay?pa={quote(upi)}&pn={payee}&am={qr_amt:.2f}&cu=INR"
        if not _draw_upi_qr(cv, payload, qx, qy, QSIZE):
            qp = _qr_img(settings)
            if qp: _draw_img_qr(cv, qp, qx, qy, QSIZE)
    else:
        qp = _qr_img(settings)
        if qp: _draw_img_qr(cv, qp, qx, qy, QSIZE)

    # ── Right: FOR label + Stamp + Signature ─────────────────────────────────
    STAMP_SZ = 28*mm
    SIGN_W   = 26*mm
    SIGN_H   = 15*mm

    # "FOR iSoftrend System" — original case, top-right
    for_text = f"FOR {settings.get('company_name','iSoftrend System')}"
    cv.setFont(fb, 9); cv.setFillColor(BLACK)
    cv.drawRightString(L+W-2*mm, y-5*mm, for_text)

    # Stamp — bottom right area
    stamp_x = L + W - STAMP_SZ - SIGN_W - 6*mm
    sp = _stamp(settings)
    if sp:
        cv.drawImage(sp, stamp_x, y-FTR_H+4*mm,
                     width=STAMP_SZ, height=STAMP_SZ,
                     preserveAspectRatio=True, mask='auto')

    # Signature — to the right of stamp
    sign_x = stamp_x + STAMP_SZ + 2*mm
    sgn = _signature(settings)
    if sgn:
        cv.drawImage(sgn, sign_x, y-FTR_H+18*mm,
                     width=SIGN_W, height=SIGN_H,
                     preserveAspectRatio=True, mask='auto')

    y -= FTR_H

    # ══════════════════════════════════════════════════════════════════════════
    # NOTES
    # ══════════════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════════════
    # NOTES
    # ══════════════════════════════════════════════════════════════════════════
    NT_H = 9*mm
    _box(cv, L, y-NT_H, W, NT_H, lw=0.5)
    cv.setFont(fb, 8); cv.setFillColor(BLACK)
    cv.drawString(L+2*mm, y-4*mm, 'Notes')
    cv.setFont(f, 7.5)
    notes_txt = (doc.get('notes') or '').strip() or 'Looking forward for your business.'
    cv.drawString(L+2*mm, y-7.5*mm, notes_txt)
    y -= NT_H

    # ══════════════════════════════════════════════════════════════════════════
    # TERMS & CONDITIONS
    # ══════════════════════════════════════════════════════════════════════════
    TRM_H = 24*mm
    _box(cv, L, y-TRM_H, W, TRM_H, lw=0.5)
    cv.setFont(fb, 8); cv.setFillColor(BLACK)
    cv.drawString(L+2*mm, y-4*mm, 'Terms & Conditions')
    cv.setFont(f, 7)
    terms_txt = (doc.get('terms') or settings.get('terms','')).strip()
    ty = y-8.5*mm
    for line in _wrap_ml(terms_txt, f, 7, W-4*mm, cv)[:5]:
        cv.drawString(L+2*mm, ty, line); ty -= 3.5*mm
    y -= TRM_H

    # ══════════════════════════════════════════════════════════════════════════
    # THANK YOU — boxed, inside outer border, at the very bottom
    # ══════════════════════════════════════════════════════════════════════════
    TY_H = 9*mm
    _box(cv, L, y-TY_H, W, TY_H, lw=0.8)
    cv.setFont(fb, 11); cv.setFillColor(BLACK)
    cv.drawCentredString(pw/2, y - TY_H/2 - 2*mm, 'THANK YOU FOR YOUR BUSINESS')
    y -= TY_H

    # ══════════════════════════════════════════════════════════════════════════
    # OUTER BORDER — wraps everything
    # ══════════════════════════════════════════════════════════════════════════
    cv.setStrokeColor(BLACK); cv.setLineWidth(1.5)
    cv.rect(L, y, W, page_top-y, stroke=1, fill=0)
