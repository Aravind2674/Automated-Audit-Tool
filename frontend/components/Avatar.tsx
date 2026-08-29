/**
 * Initials-in-circle avatar. Matches the History mockup's pattern (the only one of
 * the five that didn't use a stock headshot) -- adopted as the ONE avatar treatment
 * because our real user model (backend/models/schema.py::User) has only a
 * `username`, no photo and no display name to fake a photo caption from.
 */
export default function Avatar({ username, size = 32 }: { username: string; size?: number }) {
  const initials = username.length >= 2
    ? username.slice(0, 2).toUpperCase()
    : username.slice(0, 1).toUpperCase();

  return (
    <div
      className="flex flex-shrink-0 items-center justify-center rounded-full border border-outline-variant bg-secondary-container font-body-sm font-semibold text-on-secondary-container"
      style={{ width: size, height: size }}
      title={username}
    >
      {initials}
    </div>
  );
}
