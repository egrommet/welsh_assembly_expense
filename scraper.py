import scraperwiki
import mechanize
import urllib
import lxml.html
import re


# what we iterate over
financialyearitems = ['0', '2010', '2009', '2008']
financialmonthitems = ['', '04', '05', '06', '07', '08', '09', '10', '11', '12', '01', '02', '03']

def Main():
    for yearitem in financialyearitems[1:]:
        for monthitem in reversed(financialmonthitems[1:]):
            ScrapeMonth(yearitem, monthitem)


def ScrapeMonth(yearitem, monthitem):
    br = FetchYearFront(yearitem, monthitem)
    root = lxml.html.parse(br.response()).getroot()
    ipage, npages, nrecords = parsepagenumbers(root)
    print "****  year", yearitem, "month", monthitem, "npages", npages, "nrecords", nrecords
    if ipage == 0:
        print "skipping"
        return
    assert ipage == 1
    adddata = { "yearitem":yearitem, "monthitem":monthitem, "ipage":ipage }
    fdata = scraperwiki.sqlite.execute("select max(Number) from swdata where yearitem=? and monthitem=?", (yearitem, monthitem))

    if fdata.get("data") and fdata.get("data")[0][0] == nrecords:
        print "skipping"
        return

    pagenumbers, rowsadded = ParsePage(br, root, adddata)

    for ipage in range(2, npages+1):
        print "page", ipage, "pagenumbers", pagenumbers
        assert ipage in pagenumbers  # not possible to leap ahead beyond what is linked in this list
        dopostback(br, ('ctl00$cphMainContentsArea$grdResults','Page$%d' % ipage))
        br.submit()
        root = lxml.html.parse(br.response()).getroot()
        lipage, lnpages, lnrecords = parsepagenumbers(root)
        assert lipage == ipage
        assert lnpages == npages
        assert lnrecords == nrecords
        adddata["ipage"] = ipage
        pagenumbers, lrowsadded = ParsePage(br, root, adddata)
        rowsadded += lrowsadded
    assert npages not in pagenumbers
    assert rowsadded == nrecords, (rowsadded, nrecords)


url = 'http://www.allowances.assemblywales.org.uk/Default.aspx'
cj = mechanize.CookieJar()

def GetBrowser():
    br = mechanize.Browser()
    br.set_handle_robots(False)   # no robots
    br.set_handle_refresh(False)  # otherwise hangs
    br.addheaders = [('User-agent', 'Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.9.0.1) Gecko/2008071615 Fedora/3.0.1-1.fc9 Firefox/3.0.1')]
    br.set_cookiejar(cj)
    return br



def FetchYearFront(yearitem, monthitem):
    br = GetBrowser()
    br.open(url)
    br.select_form(name="aspnetForm")

        # clicks on image
    response = br.submit(name='ctl00$cphMainContentsArea$btnFinancialYear', coord=(3,4))  
    br.select_form(name="aspnetForm")

    lfinancialyears = [ item.name  for item in br.form.find_control('ctl00$cphMainContentsArea$ddlFinancialYear').items ]
    lfinancialfrommonths = [ item.name  for item in br.form.find_control('ctl00$cphMainContentsArea$ddlFromMonth').items ]
    lfinancialtomonths = [ item.name  for item in br.form.find_control('ctl00$cphMainContentsArea$ddlToMonth').items ]

    assert lfinancialyears == financialyearitems, lfinancialyears
    assert lfinancialfrommonths == financialmonthitems, lfinancialfrommonths
    assert lfinancialtomonths == financialmonthitems, lfinancialtomonths

    br.form['ctl00$cphMainContentsArea$ddlFinancialYear'] = [yearitem]
    br.form['ctl00$cphMainContentsArea$ddlFromMonth'] = [monthitem]
    br.form['ctl00$cphMainContentsArea$ddlToMonth'] = [monthitem]

    br.submit(name="ctl00$cphMainContentsArea$btnFind", coord=(4,5))
    return br

def parsepagenumbers(root):
    idresults = root.cssselect("#ctl00_cphMainContentsArea_lblSearchResultsPageHeader")
    assert idresults, lxml.html.tostring(root)
    if re.match("No results.", idresults[0].text):
        return 0, 0, 0
    mresults = re.match("Results: Page (\d+) of (\d+) from (\d+) result", idresults[0].text)
    assert mresults, lxml.html.tostring(idresults)
    return int(mresults.group(1)), int(mresults.group(2)), int(mresults.group(3))


def dopostback(br, dps):
    br.select_form(name="aspnetForm")
    br.form.set_all_readonly(False)
    br.form["__EVENTTARGET"] = dps[0]
    br.form["__EVENTARGUMENT"] = dps[1]

    
def ParsePage(br, root, adddata):
    br1 = GetBrowser()
    
    rows = root.cssselect("#ctl00_cphMainContentsArea_grdResults tr")
    headers = [ th.text  for th in rows[0].cssselect("th a") ]
    assert headers == ['No.', 'Member Name', 'Allowance Type', 'Expenditure Type', 'Amount'], headers
    #for i, row in enumerate(rows):
    #    print i, lxml.html.tostring(row)

            # there's a table in a the last row which gives rise to the extra row
    for i, row in enumerate(rows[1:-2]):
        values = [td.text  for td in row.cssselect("td span")]
        assert len(values) == 5, lxml.html.tostring(row)
        data = dict(zip(headers, values))
        a = row[-1][0]
        mdpb = re.match("javascript:__doPostBack\('(.*?)','(.*?)'\)", a.attrib.get("href")) 
        assert mdpb, dps
        dopostback(br, mdpb.groups())
        request = br.click()
        response = br1.open(request)
        #print response.read()

        root1 = lxml.html.parse(br1.response()).getroot()
        contents = root1.cssselect("div.mainFoldingContent")
        assert contents, lxml.html.tostring(root1)
        data["memberpage"] = lxml.html.tostring(contents[0])
        data["Number"] = int(data.pop("No."))
        data.update(adddata)
        data["i"] = i
        amount = data.pop("Amount")
        assert amount[0] == u"\xa3", amount
        data["amount"] = float(amount[1:].strip())
        scraperwiki.sqlite.save(["memberpage"], data)

    pagenumbers = [ ]
    for pl in rows[-1].cssselect("td a"):
        mpage = re.match("javascript:__doPostBack\('ctl00\$cphMainContentsArea\$grdResults','Page\$(.*?)'\)", pl.attrib.get("href"))
        assert mpage, pl.attrib.get("href")
        if mpage.group(1) in ["First", "Last"]:
            continue
        pagenumbers.append(int(mpage.group(1)))
    return pagenumbers, len(rows)-3

Main()

    


