<?php
// Pi Matrix Signage runs as its own local web service on port 8090.  Do not
// send this menu entry through FPP's page wrapper: navigating directly
// avoids the wrapper's "Unknown / Please don't access the page directly" page.
$host = (string)($_SERVER['HTTP_HOST'] ?? $_SERVER['SERVER_NAME'] ?? 'fpp.local');

// Strip an existing HTTP port while retaining bracketed IPv6 hosts.
if (preg_match('/^\[([^\]]+)\](?::\d+)?$/', $host, $m)) {
    $host = '[' . $m[1] . ']';
} elseif (substr_count($host, ':') === 1) {
    $host = preg_replace('/:\d+$/', '', $host);
}

$piMatrixUrl = 'http://' . $host . ':8090/';

if ($menu === 'content') {
    printf(
        "<li><a href='%s'>%s</a></li>\n",
        htmlspecialchars($piMatrixUrl, ENT_QUOTES),
        htmlspecialchars('Pi Matrix Signage', ENT_QUOTES)
    );
}
?>
