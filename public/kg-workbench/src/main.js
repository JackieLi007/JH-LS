import { createApp } from './app.js?v=20260514-offline-graph';

const params = new URLSearchParams(window.location.search);

createApp(document.getElementById('app'), {
  currentPage: params.get('page') || 'ontology',
  embedded: params.get('embed') === '1',
});
