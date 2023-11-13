import sys
import os
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import html_tools

# test generation guide.
# 1. Do not include encoding in the xml declaration if the test object is a str type.
# 2. Always paraphrase test.

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
def test_hotels(html_content, xpath, answer):
    html_content = html_tools.xpath_filter(xpath, html_content, append_pretty_line_formatting=True)
    assert type(html_content) == str
    assert answer in html_content



branches_to_visit = """<?xml version="1.0" ?>
  <branches_to_visit>
     <manager name="Godot" room_no="501">
         <branch>Area 51</branch>
         <branch>A place with no name</branch>
         <branch>Stalsk12</branch>
     </manager>
      <manager name="Freya" room_no="305">
         <branch>Stalsk12</branch>
         <branch>Barcelona</branch>
         <branch>Paris</branch>
     </manager>
 </branches_to_visit>"""
@pytest.mark.parametrize("html_content", [branches_to_visit])
@pytest.mark.parametrize("xpath, answer", [
    ("manager[@name = 'Godot']/branch union manager[@name = 'Freya']/branch", "Area 51"),
    ("//manager[@name = 'Godot']/branch union //manager[@name = 'Freya']/branch", "Stalsk12"),
    ("manager[@name = 'Godot']/branch | manager[@name = 'Freya']/branch", "Stalsk12"),
    ("//manager[@name = 'Godot']/branch | //manager[@name = 'Freya']/branch", "Stalsk12"),
    ("manager/branch intersect manager[@name = 'Godot']/branch", "A place with no name"),
    ("//manager/branch intersect //manager[@name = 'Godot']/branch", "A place with no name"),
    ("manager[@name = 'Godot']/branch intersect manager[@name = 'Freya']/branch", ""),
    ("manager/branch except manager[@name = 'Godot']/branch", "Barcelona"),
    ("manager[@name = 'Godot']/branch[1]  eq 'Area 51'", "true"),
    ("//manager[@name = 'Godot']/branch[1]  eq 'Area 51'", "true"),
    ("manager[@name = 'Godot']/branch[1]  eq 'Seoul'", "false"),
    ("//manager[@name = 'Godot']/branch[1]  eq 'Seoul'", "false"),
    ("manager[@name = 'Godot']/branch[2] eq manager[@name = 'Freya']/branch[2]", "false"),
    ("//manager[@name = 'Godot']/branch[2] eq //manager[@name = 'Freya']/branch[2]", "false"),
    ("manager[1]/@room_no lt manager[2]/@room_no", "false"),
    ("//manager[1]/@room_no lt //manager[2]/@room_no", "false"),
    ("manager[1]/@room_no gt manager[2]/@room_no", "true"),
    ("//manager[1]/@room_no gt //manager[2]/@room_no", "true"),
    ("manager[@name = 'Godot']/branch[1]  = 'Area 51'", "true"),
    ("//manager[@name = 'Godot']/branch[1]  = 'Area 51'", "true"),
    ("manager[@name = 'Godot']/branch[1]  = 'Seoul'", "false"),
    ("//manager[@name = 'Godot']/branch[1]  = 'Seoul'", "false"),
    ("manager[@name = 'Godot']/branch  = 'Area 51'", "true"),
    ("//manager[@name = 'Godot']/branch  = 'Area 51'", "true"),
    ("manager[@name = 'Godot']/branch  = 'Barcelona'", "false"),
    ("//manager[@name = 'Godot']/branch  = 'Barcelona'", "false"),
    ("manager[1]/@room_no > manager[2]/@room_no", "true"),
    ("//manager[1]/@room_no > //manager[2]/@room_no", "true"),
    ("manager[@name = 'Godot']/branch[ . = 'Stalsk12'] is manager[1]/branch[1]", "false"),
    ("//manager[@name = 'Godot']/branch[ . = 'Stalsk12'] is //manager[1]/branch[1]", "false"),
    ("manager[@name = 'Godot']/branch[ . = 'Stalsk12'] is manager[1]/branch[3]", "true"),
    ("//manager[@name = 'Godot']/branch[ . = 'Stalsk12'] is //manager[1]/branch[3]", "true"),
    ("manager[@name = 'Godot']/branch[ . = 'Stalsk12'] <<  manager[1]/branch[1]", "false"),
    ("//manager[@name = 'Godot']/branch[ . = 'Stalsk12'] <<  //manager[1]/branch[1]", "false"),
    ("manager[@name = 'Godot']/branch[ . = 'Stalsk12']  >>  manager[1]/branch[1]", "true"),
    ("//manager[@name = 'Godot']/branch[ . = 'Stalsk12'] >>  //manager[1]/branch[1]", "true"),
    ("manager[@name = 'Godot']/branch[ . = 'Stalsk12'] is manager[@name = 'Freya']/branch[ . = 'Stalsk12']", "false"),
    ("//manager[@name = 'Godot']/branch[ . = 'Stalsk12'] is //manager[@name = 'Freya']/branch[ . = 'Stalsk12']", "false"),
    ("manager[1]/@name || manager[2]/@name", "GodotFreya"),
    ("//manager[1]/@name || //manager[2]/@name", "GodotFreya"),
                          ])
def test_branches_to_visit(html_content, xpath, answer):
    html_content = html_tools.xpath_filter(xpath, html_content, append_pretty_line_formatting=True)
    assert type(html_content) == str
    assert answer in html_content

trips = """
<trips>
   <trip reservation_number="10">
       <depart>2023-10-06</depart>
       <arrive>2023-10-10</arrive>
       <traveler name="Christopher Anderson">
           <duration>4</duration>
           <price>2000.00</price>
       </traveler>
   </trip>
   <trip reservation_number="12">
       <depart>2023-10-06</depart>
       <arrive>2023-10-12</arrive>
       <traveler name="Frank Carter">
           <duration>6</duration>
           <price>3500.34</price>
       </traveler>
   </trip>
</trips>"""
@pytest.mark.parametrize("html_content", [trips])
@pytest.mark.parametrize("xpath, answer", [
    ("1 + 9 * 9 + 5 div 5", "83"),
    ("(1 + 9 * 9 + 5) div 6", "14.5"),
    ("23 idiv 3", "7"),
    ("23 div 3", "7.66666666"),
    ("for $i in ./trip return $i/traveler/duration * $i/traveler/price", "21002.04"),
    ("for $i in ./trip return $i/traveler/duration ", "4"),
    ("for $i in .//trip return $i/traveler/duration * $i/traveler/price", "21002.04"),
    ("sum(for $i in ./trip return $i/traveler/duration * $i/traveler/price)", "29002.04"),
    ("sum(for $i in .//trip return $i/traveler/duration * $i/traveler/price)", "29002.04"),
    #("trip[1]/depart - trip[1]/arrive", "fail_to_get_answer"),
    #("//trip[1]/depart - //trip[1]/arrive", "fail_to_get_answer"),
    #("trip[1]/depart + trip[1]/arrive", "fail_to_get_answer"),
    #("xs:date(trip[1]/depart) + xs:date(trip[1]/arrive)", "fail_to_get_answer"),
    ("(//trip[1]/arrive cast as xs:date) - (//trip[1]/depart cast as xs:date)", "P4D"),
    ("(//trip[1]/depart cast as xs:date) - (//trip[1]/arrive cast as xs:date)", "-P4D"),
    ("(//trip[1]/depart cast as xs:date) + xs:dayTimeDuration('P3D')", "2023-10-09"),
    ("(//trip[1]/depart cast as xs:date) - xs:dayTimeDuration('P3D')", "2023-10-03"),
    ("(456, 623) instance of xs:integer", "false"),
    ("(456, 623) instance of xs:integer*", "true"),
    ("/trips/trip instance of element()", "false"),
    ("/trips/trip instance of element()*", "true"),
    ("/trips/trip[1]/arrive instance of xs:date", "false"),
    ("date(/trips/trip[1]/arrive) instance of xs:date", "true"),
    ("'8' cast as xs:integer", "8"),
    ("'11.1E3' cast as xs:double", "11100"),
    ("6.5 cast as xs:integer", "6"),
    #("/trips/trip[1]/arrive cast as xs:dateTime", "fail_to_get_answer"),
    ("/trips/trip[1]/arrive cast as xs:date", "2023-10-10"),
    ("('2023-10-12') cast as xs:date", "2023-10-12"),
    ("for $i in //trip return concat($i/depart, '  ', $i/arrive)", "2023-10-06  2023-10-10"),
                          ])
def test_trips(html_content, xpath, answer):
    html_content = html_tools.xpath_filter(xpath, html_content, append_pretty_line_formatting=True)
    assert type(html_content) == str
    assert answer in html_content
