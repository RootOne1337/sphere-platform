import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { TeachingKeyBindings } from '@/src/features/stream/TeachingKeyBindings';
import { defaultTeachingProfile, type TeachingKeyRole, type TeachingProfile } from '@/src/features/stream/teachingKeymap';

function Setup({disabled=false}:{disabled?:boolean}) {
  const [profile,setProfile]=useState<TeachingProfile>(defaultTeachingProfile),[editing,setEditing]=useState<TeachingKeyRole|null>(null);
  return <><TeachingKeyBindings profile={profile} disabled={disabled} editing={editing} onEditingChange={setEditing} onChange={setProfile}/><pre data-testid="saved">{JSON.stringify(profile)}</pre></>;
}

test('capture assigns one physical key, conflict keeps the previous mapping, Escape cancels',()=>{
  render(<Setup/>);
  const forward=screen.getByRole('button',{name:'Клавиша: Вперёд / газ'}),left=screen.getByRole('button',{name:'Клавиша: Влево'});
  fireEvent.click(forward);fireEvent.keyDown(forward,{code:'ArrowUp'});
  expect(JSON.parse(screen.getByTestId('saved').textContent!).keys.forward).toBe('ArrowUp');
  fireEvent.click(left);fireEvent.keyDown(left,{code:'ArrowUp'});
  expect(screen.getByRole('status')).toHaveTextContent('уже назначена');
  expect(JSON.parse(screen.getByTestId('saved').textContent!).keys.left).toBe('KeyA');
  fireEvent.keyDown(left,{code:'Escape'});expect(left).toHaveAttribute('aria-pressed','false');
  fireEvent.click(screen.getByRole('button',{name:'По умолчанию'}));
  expect(JSON.parse(screen.getByTestId('saved').textContent!).keys).toBeUndefined();
});

test('active input disables capture and reset; modifier chords are refused while configuring',()=>{
  const view=render(<Setup/>);const forward=screen.getByRole('button',{name:'Клавиша: Вперёд / газ'});
  fireEvent.click(forward);fireEvent.keyDown(forward,{code:'KeyI',ctrlKey:true});
  expect(screen.getByRole('status')).toHaveTextContent('без Ctrl');
  expect(JSON.parse(screen.getByTestId('saved').textContent!).keys).toBeUndefined();
  view.rerender(<Setup disabled/>);expect(forward).toBeDisabled();
  expect(screen.getByRole('button',{name:'По умолчанию'})).toBeDisabled();
  fireEvent.keyDown(forward,{code:'KeyI'});
  expect(JSON.parse(screen.getByTestId('saved').textContent!).keys).toBeUndefined();
});
