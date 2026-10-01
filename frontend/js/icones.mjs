// Ícones desenhados num só traço (24×24, 1,75 px), herdando a cor do texto.
// Um conjunto pequeno e próprio: nada de glifo Unicode no lugar de ícone.
const tracos={
 resumo:'<rect x="3.5" y="3.5" width="7" height="8.5" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="5" rx="1.5"/><rect x="13.5" y="11.5" width="7" height="9" rx="1.5"/><rect x="3.5" y="15" width="7" height="5.5" rx="1.5"/>',
 explorar:'<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.4-4.4"/>',
 bancos:'<path d="M3.5 20.5h17M5.5 20.5v-9M10 20.5v-9M14 20.5v-9M18.5 20.5v-9M3 9.5 12 4l9 5.5z"/>',
 faturas:'<rect x="2.75" y="5.25" width="18.5" height="13.5" rx="2.25"/><path d="M2.75 10h18.5M6.5 15h4"/>',
 recorrencias:'<path d="M17 2.5 20.5 6 17 9.5"/><path d="M3.5 11.5v-1A4.5 4.5 0 0 1 8 6h12.5"/><path d="M7 21.5 3.5 18 7 14.5"/><path d="M20.5 12.5v1A4.5 4.5 0 0 1 16 18H3.5"/>',
 patrimonio:'<path d="M3.5 3.5v17h17"/><path d="m7.5 15 4-4.5 3 3 5.5-6"/>',
 investimentos:'<path d="M20.5 13A8.5 8.5 0 1 1 11 3.5V13z"/><path d="M14.5 3.5a7 7 0 0 1 6 6h-6z"/>',
 revisao:'<path d="m3.5 6.5 1.75 1.75L8.5 5M3.5 12.5l1.75 1.75L8.5 11M3.5 18.5l1.75 1.75L8.5 17M12.5 6.5h8M12.5 12.5h8M12.5 18.5h8"/>',
 sql:'<ellipse cx="12" cy="5.5" rx="7.5" ry="2.75"/><path d="M4.5 5.5v13c0 1.5 3.4 2.75 7.5 2.75s7.5-1.25 7.5-2.75v-13"/><path d="M4.5 12c0 1.5 3.4 2.75 7.5 2.75s7.5-1.25 7.5-2.75"/>',
 atualizar:'<path d="M20.5 12a8.5 8.5 0 0 1-14.8 5.7L3.5 15.5"/><path d="M3.5 20.5v-5h5"/><path d="M3.5 12a8.5 8.5 0 0 1 14.8-5.7l2.2 2.2"/><path d="M20.5 3.5v5h-5"/>',
 seta:'<path d="M7 17 17 7M8.5 7H17v8.5"/>',
 voltar:'<path d="M19.5 12h-15M11 18.5 4.5 12 11 5.5"/>',
 fechar:'<path d="M17.5 6.5l-11 11M6.5 6.5l11 11"/>',
 alerta:'<path d="M10.3 4.2 2.6 17.6A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-2.9L13.7 4.2a2 2 0 0 0-3.4 0z"/><path d="M12 9.5v4M12 17.25v.01"/>',
 info:'<circle cx="12" cy="12" r="8.75"/><path d="M12 16.25V11.5M12 7.75v.01"/>',
 confere:'<path d="M20 6.5 9.5 17 4 11.5"/>',
 abrir:'<path d="m6.5 9 5.5 5.5L17.5 9"/>',
 executar:'<path d="M7 4.75v14.5L19 12z"/>',
 tabela:'<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M3.5 9.5h17M9.5 9.5v10"/>',
 calendario:'<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
 filtros:'<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
 menu:'<path d="M4 7h16M4 12h16M4 17h16"/>',
 sobe:'<path d="M12 19V5M6 11l6-6 6 6"/>',
 desce:'<path d="M12 5v14M6 13l6 6 6-6"/>'
};

export function icone(nome,classe='icone'){
 return `<svg class="${classe}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${tracos[nome]??''}</svg>`;
}
