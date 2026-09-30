<?php
 header("Location: /");

$ctrl="/home/pi/boiler/boilerctl";

if (@$_GET["clear"]!==null)
{
  exec($ctrl." override clear");
  return;
}

 $min=@$_GET["min"];
 if (!$min) {
   $hour=@$_GET["hour"];
   if ($hour) $min=$hour*60;
 }
 if (!$min) {
   echo "No time paramter\n";
   return;
 }

$is_on = @$_GET["on"]!==null;
$is_off = @$_GET["off"]!==null;


if ($is_on) {   
   exec($ctrl." override $min 1");
} else if ($is_off) {   
   exec($ctrl." override $min 0");
} else {
   echo "Specify on or off";
}
?>
