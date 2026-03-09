import re
from bs4 import BeautifulSoup, NavigableString, Tag

def parse_relationship_paragraph(p):
    """
    Parse a paragraph containing legislative relationships (repeals, amendments).
    Returns a list of dictionaries, each with keys: action, regulation, procedure, link.
    Handles both 'Repealing Regulation 2010/995' and 'Amending Directive 2003/87/EC' styles.
    """
    segments = []
    current = []
    # Split by <br> tags
    for child in p.children:
        if child.name == 'br':
            if current:
                segments.append(current)
                current = []
        else:
            current.append(child)
    if current:
        segments.append(current)

    results = []
    for seg in segments:
        # Extract anchor if present
        a = next((c for c in seg if isinstance(c, Tag) and c.name == 'a'), None)
        procedure = a.get_text(strip=True) if a else None
        link = a.get('href') if a else None

        # Combine text parts to get the full string of the segment
        seg_text = ''.join(str(c) for c in seg if isinstance(c, NavigableString)).strip()

        # Determine action type and extract regulation number
        action = None
        regulation = None

        # Try to extract a regulation number: YYYY/XXXX or YYYY/XXXX/SUFFIX (e.g., 2003/87/EC)
        reg_match = re.search(r'(\d{4}/\d+(?:/[A-Z]+)?)', seg_text)
        if reg_match:
            regulation = reg_match.group(1)

        # Determine action based on keywords
        if 'Repealing' in seg_text:
            action = 'Repealing Regulation'
        elif 'Amended by' in seg_text:
            action = 'Amended by'
        elif 'Repealed by' in seg_text:
            action = 'Repealed by'
        elif 'Amending' in seg_text:
            # Could be "Amending Directive", "Amending Regulation", etc.
            # Extract the part before the regulation number, if possible
            if reg_match:
                # Get the text before the regulation number
                before_reg = seg_text[:reg_match.start()].strip()
                if before_reg:
                    action = before_reg
                else:
                    action = 'Amending'  # fallback
            else:
                action = 'Amending'
        else:
            # If no keyword, use the whole text as action (fallback)
            action = seg_text

        # If we still have no action, set a default
        if not action:
            action = 'Unknown'

        results.append({
            'action': action,
            'regulation': regulation,
            'procedure': procedure,
            'link': link
        })
    return results

def parse_subjects(p):
    """
    Parse a paragraph containing subject codes and names separated by <br/>.
    Returns a list of dictionaries with keys: code, name.
    """
    # Get the text with newline as a separator, then split into non-empty lines
    text = p.get_text(separator='\n', strip=True)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    subjects = []
    for line in lines:
        # Split only on the first space to separate code and name
        parts = line.split(' ', 1)
        code = parts[0] if parts else ''
        name = parts[1] if len(parts) > 1 else ''
        subjects.append({'code': code, 'name': name})
    return subjects

def extract_basic_info(soup):
    """
    Extract basic information from the procedure page and return a list of
    rows (dicts) with keys 'meta_column' and 'value'.
    """
    rows = []

    # Title (outside section1)
    title_h2 = soup.find('h2', class_='es_title-h2 mb-3')
    if title_h2:
        rows.append({'meta_column': 'title', 'value': title_h2.get_text(strip=True)})

    # Locate the Basic information section
    section = soup.find('div', id='section1')
    if not section:
        return rows

    left_col = section.find('div', class_='col-6')
    if not left_col:
        return rows

    # --- policy id ---
    ref_p = left_col.find('p', class_='font-weight-bold mb-1')
    if ref_p and 'COD' in ref_p.get_text():
        rows.append({'meta_column': 'policy_id', 'value': ref_p.get_text(strip=True)})

    # --- procedure type ---
    proc_p = left_col.find('p', string=lambda s: s and 'COD -' in s)
    if proc_p:
        rows.append({'meta_column': 'procedure_type', 'value': proc_p.get_text(strip=True)})

    # --- act type ---
    act_p = left_col.find('p', string=lambda s: s and s.strip() in ['Regulation', 'Directive', 'Decision'])
    if act_p:
        rows.append({'meta_column': 'act_type', 'value': act_p.get_text(strip=True)})

    # --- relationships (repeals, amendments) ---
    # Find the paragraph that contains any <a> with href containing "reference="
    rel_p = None
    for p in left_col.find_all('p'):
        if p.find('a', href=re.compile(r'reference=')):
            rel_p = p
            break
    if rel_p:
        rels = parse_relationship_paragraph(rel_p)
        for idx, rel in enumerate(rels, start=1):
            if rel['action']:
                rows.append({'meta_column': f'action_{idx}', 'value': rel['action']})
            if rel['regulation']:
                rows.append({'meta_column': f'regulation_{idx}', 'value': rel['regulation']})
            if rel['procedure']:
                rows.append({'meta_column': f'procedure_{idx}', 'value': rel['procedure']})
            if rel['link']:
                rows.append({'meta_column': f'procedure_link_{idx}', 'value': rel['link']})

    # --- subjects ---
    subject_label = left_col.find('p', class_='font-weight-bold mb-1', string=lambda s: s and 'Subject' in s)
    if subject_label:
        subject_p = subject_label.find_next_sibling('p')
        if subject_p:
            subjects = parse_subjects(subject_p)
            for idx, subj in enumerate(subjects, start=1):
                if subj['code']:
                    rows.append({'meta_column': f'subject_code_{idx}', 'value': subj['code']})
                if subj['name']:
                    rows.append({'meta_column': f'subject_{idx}', 'value': subj['name']})

    # --- status (from right column) ---
    right_cols = section.find_all('div', class_='col-6')
    if len(right_cols) > 1:
        right_col = right_cols[1]
        status_p = right_col.find('p', class_='text-danger')
        if status_p:
            status_text = status_p.get_text(strip=True).lower().replace('procedure ', '')
            rows.append({'meta_column': 'status', 'value': status_text})

    return rows

def extract_key_players_long(soup):
    """
    Extract key players data from the procedure page and return a list of
    rows (dicts) with keys 'meta_column' and 'value'.
    """
    rows = []

    # Locate the Key players section
    section = soup.find('div', id='section2')
    if not section:
        return rows

    # Find all accordion items (European Parliament, Commission, etc.)
    accordion_items = section.find_all('li', class_='es_accordion-item')
    for item in accordion_items:
        # Get the title (e.g., "European Parliament")
        title_button = item.find('button', class_='es_accordion-item-title')
        if not title_button:
            continue
        title_span = title_button.find('span', class_='t-x')
        title = title_span.get_text(strip=True) if title_span else ''

        # Get the content div
        content_div = item.find('div', class_='es_accordion-item-content')
        if not content_div:
            continue

        # --- European Parliament ---
        if title == 'European Parliament':
            tables = content_div.find_all('table', class_='table-bordered')
            # First table: lead committee + rapporteur + shadow rapporteurs
            if len(tables) >= 1:
                lead_table = tables[0]
                tbody = lead_table.find('tbody')
                if tbody:
                    # Find the main row (first <tr> that contains committee info)
                    main_row = tbody.find('tr')
                    if main_row:
                        # --- Lead committee table: try current, then former ---
                        lead_table = None
                        for table in content_div.find_all('table', class_='table-bordered'):
                            thead = table.find('thead')
                            if thead and 'Committee responsible' in thead.get_text():
                                lead_table = table
                                break
                        if not lead_table:
                            for table in content_div.find_all('table', class_='table-bordered'):
                                thead = table.find('thead')
                                if thead and 'Former committee responsible' in thead.get_text():
                                    lead_table = table
                                    break

                        if lead_table:
                            tbody = lead_table.find('tbody')
                            if tbody:
                                main_row = tbody.find('tr')
                                if main_row:
                                    # ---- Lead committee code & name ----
                                    th_committee = main_row.find('th')
                                    if th_committee:
                                        badge = th_committee.find('span', class_='es_badge-committee')
                                        code = badge.get_text(strip=True) if badge else ''
                                        name_span = th_committee.find('span', class_='font-weight-normal')
                                        name = name_span.get_text(strip=True) if name_span else ''
                                        rows.append({'meta_column': 'EP lead committee code', 'value': code})
                                        rows.append({'meta_column': 'EP lead committee', 'value': name})

                        # ---- Rapporteur ----
                        rapporteur_td = main_row.find_all('td')[0]  # first td after th
                        if rapporteur_td:
                            a_rapp = rapporteur_td.find('a', class_='rapporteur')
                            if a_rapp:
                                full_text = a_rapp.get_text(strip=True)
                                # Parse name and group (format: "SURNAME Name (GROUP)")
                                group_match = re.search(r'\(([^)]+)\)', full_text)
                                group = group_match.group(1) if group_match else ''
                                name = full_text.replace(f'({group})', '').strip() if group else full_text
                                rows.append({'meta_column': 'Rapporteur', 'value': name})
                                rows.append({'meta_column': 'Rapporteur group', 'value': group})
                                link = a_rapp.get('href')
                                if link:
                                    rows.append({'meta_column': 'Rapporteur link', 'value': link})

                        # ---- Appointment date ----
                        date_td = main_row.find_all('td')[1]  # second td
                        if date_td:
                            date_span = date_td.find('span')
                            date = date_span.get_text(strip=True) if date_span else ''
                            rows.append({'meta_column': 'Appointment date', 'value': date})

                    # ---- Shadow rapporteurs (inside a collapse) ----
                    # Find the row containing the shadow button
                    shadow_row = None
                    for row in tbody.find_all('tr'):
                        button = row.find('button', {'data-target': '#collapseShadowRapporteur'})
                        if button:
                            shadow_row = row
                            break
                    if shadow_row:
                        shadow_td = shadow_row.find('td', class_='border-0')
                        if shadow_td:
                            collapse_div = shadow_td.find('div', class_='collapse', id='collapseShadowRapporteur')
                            if collapse_div:
                                shadow_links = collapse_div.find_all('a', class_='rapporteur')
                                for idx, a in enumerate(shadow_links, start=1):
                                    full_text = a.get_text(strip=True)
                                    group_match = re.search(r'\(([^)]+)\)', full_text)
                                    group = group_match.group(1) if group_match else ''
                                    name = full_text.replace(f'({group})', '').strip() if group else full_text
                                    rows.append({'meta_column': f'Shadow rapporteur_{idx}', 'value': name})
                                    rows.append({'meta_column': f'Shadow rapporteurs group_{idx}', 'value': group})
                                    link = a.get('href')
                                    if link:
                                        rows.append({'meta_column': f'Shadow rapporteurs link_{idx}', 'value': link})

            # --- Committees for opinion: try current, then former ---
            opinion_table = None
            for table in content_div.find_all('table', class_='table-bordered'):
                thead = table.find('thead')
                if thead and 'Committee for opinion' in thead.get_text():
                    opinion_table = table
                    break
            if not opinion_table:
                for table in content_div.find_all('table', class_='table-bordered'):
                    thead = table.find('thead')
                    if thead and 'Former committee for opinion' in thead.get_text():
                        opinion_table = table
                        break

            if opinion_table:
                tbody = opinion_table.find('tbody')
                if tbody:
                    opinion_rows = tbody.find_all('tr')
                    for idx, row in enumerate(opinion_rows, start=1):
                        cells = row.find_all(['th', 'td'])
                        if len(cells) >= 3:
                            # Committee code and name
                            th_comm = cells[0]
                            badge = th_comm.find('span', class_='es_badge-committee')
                            code = badge.get_text(strip=True) if badge else ''
                            name_span = th_comm.find('span', class_='font-weight-normal')
                            name = name_span.get_text(strip=True) if name_span else ''
                            rows.append({'meta_column': f'Committee for opinion_{idx}', 'value': name})
                            rows.append({'meta_column': f'Committee for opinion_{idx} code', 'value': code})

                            # Rapporteur for opinion
                            rapporteur_td = cells[1]
                            a_rapp = rapporteur_td.find('a', class_='rapporteur')
                            if a_rapp:
                                full_text = a_rapp.get_text(strip=True)
                                group_match = re.search(r'\(([^)]+)\)', full_text)
                                group = group_match.group(1) if group_match else ''
                                rapp_name = full_text.replace(f'({group})', '').strip() if group else full_text
                                rows.append({'meta_column': f'Com_op_{idx} rapporteurs', 'value': rapp_name})
                                rows.append({'meta_column': f'Com_op_{idx} rapporteurs group', 'value': group})
                                link = a_rapp.get('href')
                                if link:
                                    rows.append({'meta_column': f'Com_op_{idx} rapporteurs link', 'value': link})

                                # Appointment date (only if rapporteur exists)
                                date_td = cells[2]
                                date_span = date_td.find('span')
                                date = date_span.get_text(strip=True) if date_span else ''
                                if date:
                                    rows.append({'meta_column': f'Com_op_{idx} rapporteurs appt date', 'value': date})
                            # else: no rapporteur → committee code and name already stored

        # --- Council of the European Union (new) ---
        elif title == 'Council of the European Union':
            table = content_div.find('table', class_='table-bordered')
            if table:
                tbody = table.find('tbody')
                if tbody:
                    council_rows = tbody.find_all('tr')
                    for idx, row in enumerate(council_rows, start=1):
                        cells = row.find_all(['th', 'td'])
                        if len(cells) >= 3:
                            # ---- Council configuration ----
                            th_conf = cells[0]
                            a_conf = th_conf.find('a')
                            if a_conf:
                                conf_name = a_conf.get_text(strip=True)
                                conf_link = a_conf.get('href')
                            else:
                                conf_name = th_conf.get_text(strip=True)
                                conf_link = None
                            rows.append({'meta_column': f'Council configuration_{idx}', 'value': conf_name})
                            if conf_link:
                                rows.append({'meta_column': f'Council configuration_{idx}_link', 'value': conf_link})

                            # ---- Meeting number ----
                            td_meeting = cells[1]
                            a_meeting = td_meeting.find('a')
                            if a_meeting:
                                meeting_num = a_meeting.get_text(strip=True)
                                meeting_link = a_meeting.get('href')
                            else:
                                meeting_num = td_meeting.get_text(strip=True)
                                meeting_link = None
                            rows.append({'meta_column': f'Council meeting number_{idx}', 'value': meeting_num})
                            if meeting_link:
                                rows.append({'meta_column': f'Council meeting number_{idx}_link', 'value': meeting_link})

                            # ---- Date ----
                            td_date = cells[2]
                            date = td_date.get_text(strip=True)
                            rows.append({'meta_column': f'Council meeting_{idx} date', 'value': date})

                            
        # --- European Commission ---
        elif title == 'European Commission':
            table = content_div.find('table', class_='table-bordered')
            if table:
                tbody = table.find('tbody')
                if tbody:
                    row = tbody.find('tr')
                    if row:
                        cells = row.find_all(['th', 'td'])
                        if len(cells) >= 2:
                            # DG
                            dg_th = cells[0]
                            a_dg = dg_th.find('a')
                            dg = a_dg.get_text(strip=True) if a_dg else dg_th.get_text(strip=True)
                            rows.append({'meta_column': 'Commission DG', 'value': dg})

                            # Commissioner
                            comm_td = cells[1]
                            span_comm = comm_td.find('span')
                            commissioner = span_comm.get_text(strip=True) if span_comm else comm_td.get_text(strip=True)
                            rows.append({'meta_column': 'Commissioner', 'value': commissioner})

        # (Optional) You can add parsing for Council, EESC, CoR if needed later.

    return rows

def extract_mandatory_consultation(soup):
    """
    Extract mandatory consultation bodies from the Technical Information section.
    Returns a list of dicts with keys 'meta_column' and 'value'.
    """
    rows = []
    section = soup.find('div', id='section5')
    if not section:
        return rows

    # Locate the table inside the section
    table = section.find('table', class_='table-bordered')
    if not table:
        return rows

    # Find the row whose header contains the exact phrase
    for tr in table.find_all('tr'):
        th = tr.find('th')
        if th and 'Mandatory consultation of other institutions' in th.get_text(strip=True):
            td = tr.find('td')
            if td:
                # Look for all <a> tags (they may have class "d-block")
                anchors = td.find_all('a')
                for idx, a in enumerate(anchors, start=1):
                    name = a.get_text(strip=True)
                    link = a.get('href')
                    rows.append({
                        'meta_column': f'Mandatory consultation of other institutions_{idx}',
                        'value': name
                    })
                    if link:
                        rows.append({
                            'meta_column': f'Mandatory consultation of other institutions_{idx}_link',
                            'value': link
                        })
                # If no <a> tags, but there might be plain text (fallback)
                if not anchors:
                    # Get all text nodes inside td (e.g. if institution names are in <span>)
                    for span in td.find_all('span'):
                        name = span.get_text(strip=True)
                        rows.append({
                            'meta_column': f'Mandatory consultation of other institutions_{idx}',
                            'value': name
                        })
            break  # stop after processing the correct row
    return rows