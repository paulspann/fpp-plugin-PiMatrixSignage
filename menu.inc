<?php
$menuEntries = array(
    array(
        'text' => 'Pi Matrix Signage',
        'type' => 'content',
        'page' => 'content.php',
        'wrap' => 1
    )
);

foreach ($menuEntries as $entry) {
    if ($entry['type'] != $menu) continue;
    $nopage = '';
    if (isset($entry['wrap']) && ($entry['wrap'] == 0)) $nopage = '&nopage=1';
    printf("<li><a href='plugin.php?_menu=%s&page=%s%s'>%s</a></li>\n",
        htmlspecialchars($plugin, ENT_QUOTES),
        htmlspecialchars($entry['page'], ENT_QUOTES),
        $nopage,
        htmlspecialchars($entry['text'], ENT_QUOTES));
}
?>
