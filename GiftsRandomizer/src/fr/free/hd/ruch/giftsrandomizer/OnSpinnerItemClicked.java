package fr.free.hd.ruch.giftsrandomizer;

import android.view.View;
import android.widget.AdapterView;
import android.widget.AdapterView.OnItemSelectedListener;
import fr.free.hd.ruch.giftsrandomizer.people.Group;

public class OnSpinnerItemClicked implements OnItemSelectedListener {

	Group selectedItem;

	public Group getSelectedItem() {
		return selectedItem;
	}

	@Override
	public void onItemSelected(AdapterView<?> parent, View view, int pos, long id) {
		selectedItem = (Group) parent.getItemAtPosition(pos);
	}

	@Override
	public void onNothingSelected(AdapterView<?> parent) {
		// TODO Auto-generated method stub

	}
}
