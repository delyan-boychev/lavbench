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
  return zones.map((zone) => ({
    value: zone,
    label: zone.replace(/_/g, ' '),
  }));
};

export const TIMEZONES = getTimezones();
