<?php
 $s=file_get_contents('/sys/class/gpio/gpio4/value');
 $stxt=($s[0]=="1" ? 'off':'on');
?>
<html>
<head>
	<title>Boiler is <?=($stxt)?></title>
</head>
<body style="width:100%">
<style>
h1 {
width:100%;
font-size: 48px;
}
.on {
background: orange;
}
.off {
background: blue;
}
td {
  padding: 5px;
}

</style>
<h1 class="<?=($stxt)?>">Boiler is <?=($stxt)?></h1>
<?php
echo "Local time is now:".strftime("%T");
$filename='/tmp/override';
if (file_exists($filename))
{
  $o=file_get_contents($filename);
  if ($o != "") {
     $a=split(' ', $o);
     $start=filemtime($filename);
     $end=$start+$a[0]*60;
     $until=strftime("%R",$end);
     $l=$end-time();
     $m=intval($l/60); $l-=$m*60;
     $h=intval($m/60); $m-=$h*60;
     if ($h==0)
            echo "<h3>override for ".sprintf("%02d:%02d",$m,$l)." until $until it will be $a[1]</h3>";
     else
            echo "<h3>override for ".sprintf("%d:%02d:%02d",$h,$m,$l)." until $until it will be $a[1]</h3>";

  }
}
$filename='/tmp/sched.data';

  $a=file($filename);
?>
<h3>Daily schedule below:</h3>
<table border="1" style="border: 1px black;">
<tr><th>Day</th><th>Start Time</th><th>End Time</th></tr>
<?php
  $days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  foreach ($a as $v) {
     $a=split(' ', $v);
	 if (count($a)==1) $d = "any";
	 else {
		$d = $days[$a[0]-1];
		$v = $a[1];
	 }
     $s=split('-',$v);
     echo "<tr><td>$d</td><td>$s[0]</td><td>$s[1]</td></tr>";
  }
?>
</table>
<h3>For manuall on/off click the links below:</h3>
<table border="1">
<tr><th class='off'>Turn Off</th><th class='on'>Turn On</th></tr>
<tr>
   <td>
      <a href="/setup.php?hour=1&off">1 hour</a>
   </td><td>
      <a href="/setup.php?hour=1&on">1 hour</a>
   </td>
</tr>
<tr>
   <td>
      <a href="/setup.php?hour=2&off">2 hour</a>
   </td><td>
      <a href="/setup.php?hour=2&on">2 hour</a>
   </td>
</tr>
<tr>
   <td>
      <a href="/setup.php?hour=4&off">4 hour</a>
   </td><td>
      <a href="/setup.php?hour=4&on">4 hour</a>
   </td>
</tr>
<tr>
   <td>
      <a href="/setup.php?hour=8&off">8 hour</a>
   </td><td>
      <a href="/setup.php?hour=8&on">8 hour</a>
   </td>
</tr>
</table>
<br/>
<b><a href="/setup.php?clear">Clear manual override</b>
<br/>
<br/>
<br/>
<a href="/data">Data</a>
