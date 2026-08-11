import { createApp } from './app.js?v=20260601-large-table-fix';

const params = new URLSearchParams(window.location.search);

async function bootstrap() {
  try {
    const response = await fetch('/api/auth/me', {
      cache: 'no-store',
      credentials: 'include',
    });
    const payload = await response.json();
    const user = payload?.result;
    if (!response.ok || user?.role !== 'editor') {
      window.top.location.replace(user?.homePath || '/login');
      return;
    }
  } catch {
    window.top.location.replace('/login');
    return;
  }

  createApp(document.getElementById('app'), {
    currentPage: params.get('page') || 'ontology',
    embedded: params.get('embed') === '1',
  });
}

void bootstrap();
