<?php

function verify(bool $condition, string $message): void
{
    if (!$condition) {
        http_response_code(500);
        throw new RuntimeException($message);
    }
}

verify(PHP_MAJOR_VERSION === 8 && PHP_MINOR_VERSION === 4, PHP_VERSION);
verify(php_ini_loaded_file() === '/etc/php84/php.ini', 'Unexpected php.ini');
foreach (['apcu', 'ctype', 'curl', 'dom', 'enchant', 'exif', 'fileinfo', 'gd', 'iconv',
          'intl', 'mbstring', 'openssl', 'PDO', 'pdo_mysql', 'pdo_pgsql', 'pdo_sqlite',
          'session', 'SimpleXML', 'sockets', 'sodium', 'tidy', 'xml', 'xmlreader',
          'xmlwriter', 'zip', 'snuffleupagus', 'Zend OPcache'] as $module) {
    verify(extension_loaded($module), "Missing PHP extension: $module");
}
verify(ini_get('sp.configuration_file') === '/etc/snuffleupagus.rules', 'Missing rules path');
ob_start();
phpinfo(INFO_MODULES);
$modules = strip_tags(ob_get_clean());
verify(preg_match('/snuffleupagus support\s*(?:=>\s*)?enabled/i', $modules) === 1,
    'Snuffleupagus did not activate the configuration');

$broker = enchant_broker_init();
foreach (['en_US', 'en_GB', 'de', 'fr', 'ru', 'uk'] as $locale) {
    verify(enchant_broker_dict_exists($broker, $locale), "Missing dictionary: $locale");
    $dictionary = enchant_broker_request_dict($broker, $locale);
    verify(enchant_dict_describe($dictionary)['name'] === 'aspell', "Unexpected backend: $locale");
}

if (str_contains(__DIR__, '/roundcube/')) {
    define('INSTALL_PATH', dirname(__DIR__) . '/');
    require INSTALL_PATH . 'program/include/iniset.php';
    verify(version_compare(RCMAIL_VERSION, '1.6.21', '>='), RCMAIL_VERSION);
    $spellcheck = new rcube_spellchecker('en');
    verify($spellcheck->check('hello') && !$spellcheck->check('heloo'), 'Roundcube spellcheck failed');
    echo 'Roundcube ', RCMAIL_VERSION, "\n";
}

echo PHP_SAPI, ' PHP ', PHP_VERSION, " with active Snuffleupagus rules and Aspell dictionaries\n";
