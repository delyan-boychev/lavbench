const getTimezones = () => {
  let zones;
  try {
    zones = Intl.supportedValuesOf('timeZone');
  } catch {
    zones = [
      'UTC',
      'Europe/Sofia',
      'Europe/London',
      'Europe/Paris',
      'Europe/Berlin',
      'Europe/Athens',
      'Europe/Bucharest',
      'Europe/Rome',
      'Europe/Madrid',
      'Europe/Dublin',
      'America/New_York',
      'America/Chicago',
      'America/Denver',
      'America/Los_Angeles',
      'America/Toronto',
      'America/Mexico_City',
      'America/Sao_Paulo',
      'Asia/Tokyo',
      'Asia/Shanghai',
      'Asia/Singapore',
      'Asia/Kolkata',
      'Asia/Dubai',
      'Australia/Sydney',
      'Australia/Melbourne',
      'Africa/Cairo',
      'Africa/Johannesburg',
      'Pacific/Auckland',
    ];
  }
  // Browsers list no 'UTC', yet it is every competition's default, so the select needs it
  if (!zones.includes('UTC')) zones = ['UTC', ...zones];
  return zones.map((zone) => ({
    value: zone,
    label: zone.replace(/_/g, ' '),
  }));
};

export const TIMEZONES = getTimezones();

/** The browser's own time zone when the list offers it, so new competitions start there. */
export function browserTimeZone() {
  let zone = '';
  try {
    zone = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  } catch {
    zone = '';
  }
  return TIMEZONES.some((option) => option.value === zone) ? zone : 'UTC';
}
