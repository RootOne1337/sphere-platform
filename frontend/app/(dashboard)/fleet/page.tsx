import { redirect } from 'next/navigation';

// Keep existing bookmarks while using the same maintained group workflow as the sidebar.
export default function FleetPage() {
  return redirect('/groups');
}
