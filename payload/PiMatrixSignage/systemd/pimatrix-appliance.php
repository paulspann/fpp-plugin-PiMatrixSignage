<?php
// Customer appliance entry point. Keep FPP's explicit /index.php untouched for
// engineering/support and keep all /api routes available to Pi Matrix itself.
$rawHost = $_SERVER['HTTP_HOST'] ?? ($_SERVER['SERVER_ADDR'] ?? 'fpp.local');
$host = $rawHost;
if (preg_match('/^\[([^\]]+)\](?::\d+)?$/', $rawHost, $m)) {
    $host = '[' . $m[1] . ']';
} elseif (preg_match('/^([^:]+)(?::\d+)?$/', $rawHost, $m)) {
    $host = $m[1];
}
header('Cache-Control: no-store');
header('Location: http://' . $host . ':8090/', true, 302);
exit;
