<?php
$versionFile = '/home/fpp/media/pi-matrix-signage/VERSION';
$installed = is_file($versionFile);
$version = $installed ? trim((string) @file_get_contents($versionFile)) : '';
$service = trim((string) @shell_exec('systemctl is-active pi-matrix-signage.service 2>/dev/null'));
$active = ($service === 'active');
$health = false;
if ($active) {
    $ctx = stream_context_create(['http' => ['timeout' => 1, 'ignore_errors' => true]]);
    $raw = @file_get_contents('http://127.0.0.1:8090/health', false, $ctx);
    if (is_string($raw) && $raw !== '') {
        $decoded = json_decode($raw, true);
        $health = is_array($decoded) ? !empty($decoded['ok']) : true;
    }
}
?>
<div class="container-fluid px-0">
  <div class="card mt-2">
    <div class="card-header d-flex justify-content-between align-items-center">
      <strong>Pi Matrix Signage</strong>
      <span class="badge <?= $active && $health ? 'text-bg-success' : ($installed ? 'text-bg-warning' : 'text-bg-secondary') ?>">
        <?= $active && $health ? 'Running' : ($installed ? 'Needs attention' : 'Not installed') ?>
      </span>
    </div>
    <div class="card-body">
      <p class="mb-3">Pi Matrix Signage is installed and maintained through the FPP Plugin Manager. No SSH or command-line installation is required.</p>
      <div class="row g-3 mb-3">
        <div class="col-12 col-md-4">
          <div class="border rounded p-3 h-100">
            <div class="text-body-secondary small">Application</div>
            <div class="fw-semibold"><?= $installed ? 'Installed' : 'Not installed' ?></div>
          </div>
        </div>
        <div class="col-12 col-md-4">
          <div class="border rounded p-3 h-100">
            <div class="text-body-secondary small">Version</div>
            <div class="fw-semibold"><?= htmlspecialchars($version ?: '—', ENT_QUOTES) ?></div>
          </div>
        </div>
        <div class="col-12 col-md-4">
          <div class="border rounded p-3 h-100">
            <div class="text-body-secondary small">Service</div>
            <div class="fw-semibold"><?= htmlspecialchars($service ?: 'unknown', ENT_QUOTES) ?></div>
          </div>
        </div>
      </div>
      <?php if ($active): ?>
        <button type="button" class="btn btn-primary" id="openPiMatrix">Open Pi Matrix Signage</button>
        <span class="ms-2 text-body-secondary small">Opens the controller on port 8090.</span>
      <?php else: ?>
        <div class="alert alert-warning mb-0">Pi Matrix Signage is not currently running. Use the FPP Plugin Manager to reinstall/update this plugin. The installer will health-check the service automatically.</div>
      <?php endif; ?>
      <?php if ($installed): ?>
        <hr>
        <p class="mb-1"><strong>First installation:</strong> open Pi Matrix Signage and complete the initial password change, then enter the PMS licence under Software licence.</p>
        <p class="mb-0 text-body-secondary small">Message, schedule, media and licence data are stored separately from the replaceable application files so plugin updates preserve your configuration.</p>
      <?php endif; ?>
    </div>
  </div>
</div>
<script>
(() => {
  const b = document.getElementById('openPiMatrix');
  if (!b) return;
  b.addEventListener('click', () => {
    const host = window.location.hostname;
    window.open('http://' + host + ':8090/', '_blank', 'noopener');
  });
})();
</script>
