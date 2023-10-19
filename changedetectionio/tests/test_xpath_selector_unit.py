import sys
import os
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import html_tools

# test generation guide.
# 1. Do not include encoding in the xml declaration if the test object is a str type.
# 2. Always paraphrase test.
# 3. The test material must not include the tags commonly used in HTML.

hotels = """
<hotel>
  <branch location="California">
    <staff>
      <given_name>Christopher</given_name>
      <surname>Anderson</surname>
      <age>25</age>
    </staff>
    <staff>
      <given_name>Christopher</given_name>
      <surname>Carter</surname>
      <age>30</age>
    </staff>
  </branch>
  <branch location="Las Vegas">
    <staff>
      <given_name>Lisa</given_name>
      <surname>Walker</surname>
      <age>60</age>
    </staff>
    <staff>
      <given_name>Jessica</given_name>
      <surname>Walker</surname>
      <age>32</age>
    </staff>
    <staff>
      <given_name>Jennifer</given_name>
      <surname>Roberts</surname>
      <age>50</age>
    </staff>
  </branch>
</hotel>"""

@pytest.mark.parametrize("html_content", [hotels])
@pytest.mark.parametrize("xpath, answer", [('(//staff/given_name, //staff/age)', '25'),
                          ("xs:date('2023-10-10')", '2023-10-10'),
                          ("if (/hotel/branch[@location = 'California']/staff[1]/age = 25) then 'is 25' else 'is not 25'", 'is 25'),
                          ("if (//hotel/branch[@location = 'California']/staff[1]/age = 25) then 'is 25' else 'is not 25'", 'is 25'),
                          ("if (count(/hotel/branch/staff) = 5) then true() else false()", 'true'),
                          ("if (count(//hotel/branch/staff) = 5) then true() else false()", 'true'),
                          ("for $i in /hotel/branch/staff return if ($i/age >= 40) then upper-case($i/surname) else lower-case($i/surname)", 'anderson'),
                          ("given_name  =  'Christopher' and age  =  40", 'false'),
                          ("//given_name  =  'Christopher' and //age  =  40", 'false'),
                          #("(staff/given_name, staff/age)", 'Lisa'),
                          ("(//staff/given_name, //staff/age)", 'Lisa'),
                          #("hotel/branch[@location = 'California']/staff/age union hotel/branch[@location = 'Las Vegas']/staff/age", ''),
                          ("(//hotel/branch[@location = 'California']/staff/age union //hotel/branch[@location = 'Las Vegas']/staff/age)", '60'),
                          ("(200 to 210)", "205"),
                          ("(//hotel/branch[@location = 'California']/staff/age union //hotel/branch[@location = 'Las Vegas']/staff/age)", "50"),
                          ("(1, 9, 9, 5)", "5"),
                          ("(3, (), (14, 15), 92, 653)", "653"),
                          ("for $i in /hotel/branch/staff return $i/given_name", "Christopher"),
                          ("for $i in //hotel/branch/staff return $i/given_name", "Christopher"),
                          ("distinct-values(for $i in /hotel/branch/staff return $i/given_name)", "Jessica"),
                          ("distinct-values(for $i in //hotel/branch/staff return $i/given_name)", "Jessica"),
                          ("for $i in (7 to  15) return $i*10", "130"),
                          ("some $i in /hotel/branch/staff satisfies $i/age < 20", "false"),
                          ("some $i in //hotel/branch/staff satisfies $i/age < 20", "false"),
                          ("every $i in /hotel/branch/staff satisfies $i/age > 20", "true"),
                          ("every $i in //hotel/branch/staff satisfies $i/age > 20 ", "true"),
                          ("let $x := branch[@location = 'California'], $y := branch[@location = 'Las Vegas'] return (avg($x/staff/age), avg($y/staff/age))", "27.5"),
                          ("let $x := //branch[@location = 'California'], $y := //branch[@location = 'Las Vegas'] return (avg($x/staff/age), avg($y/staff/age))", "27.5"),
                          ("let $nu := 1, $de := 1000 return  'probability = ' || $nu div $de * 100 || '%'", "0.1%"),
                          ("let $nu := 2, $probability := function ($argument) { 'probability = ' ||  $nu div $argument  * 100 || '%'}, $de := 5 return $probability($de)", "40%"),
                          ("'XPATH2.0-3.1 dissemination' instance of xs:string ", "true"),
                          ("'new stackoverflow question incoming' instance of xs:integer ", "false"),
                          ("'50000' cast as xs:integer", "50000"),
                          ("//branch[@location = 'California']/staff[1]/surname eq 'Anderson'", "true"),
                          ("fn:false()", "false")])
def test_sample(html_content, xpath, answer):
    html_content = html_tools.xpath_filter(xpath, html_content, append_pretty_line_formatting=True)
    assert type(html_content) == str
    assert answer in html_content
