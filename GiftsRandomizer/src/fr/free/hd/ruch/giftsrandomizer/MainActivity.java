package fr.free.hd.ruch.giftsrandomizer;

import java.util.ArrayList;
import java.util.List;

import android.annotation.SuppressLint;
import android.app.ActionBar;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.Fragment;
import android.app.FragmentManager;
import android.content.DialogInterface;
import android.os.Bundle;
import android.support.v4.widget.DrawerLayout;
import android.view.LayoutInflater;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.ListView;
import android.widget.Spinner;
import android.widget.Toast;
import fr.free.hd.ruch.giftsrandomizer.people.Group;

public class MainActivity extends Activity implements NavigationDrawerFragment.NavigationDrawerCallbacks {

	// FIXME
	private List<Group> myGroups;
	private ArrayAdapter<Group> adapter;
	/**
	 * Fragment managing the behaviors, interactions and presentation of the navigation drawer.
	 */
	private NavigationDrawerFragment mNavigationDrawerFragment;

	/**
	 * Used to store the last screen title. For use in {@link #restoreActionBar()}.
	 */
	private CharSequence mTitle;

	public final static String EXTRA_MESSAGE = "fr.free.hd.ruch.giftsrandomizer.MESSAGE";

	@Override
	protected void onCreate(Bundle savedInstanceState) {
		super.onCreate(savedInstanceState);
		setContentView(R.layout.activity_main);

		mNavigationDrawerFragment = (NavigationDrawerFragment) getFragmentManager().findFragmentById(R.id.navigation_drawer);
		mTitle = getTitle();

		// Set up the drawer.
		mNavigationDrawerFragment.setUp(R.id.navigation_drawer, (DrawerLayout) findViewById(R.id.drawer_layout));

		myGroups = new ArrayList<Group>();
		adapter = new ArrayAdapter<Group>(this, android.R.layout.simple_list_item_1, myGroups);
	}

	@Override
	public void onNavigationDrawerItemSelected(int position) {
		// update the main content by replacing fragments
		FragmentManager fragmentManager = getFragmentManager();
		fragmentManager.beginTransaction().replace(R.id.container, PlaceholderFragment.newInstance(position + 1)).commit();
	}

	public void onSectionAttached(int number) {
		switch (number) {
		case 1:
			mTitle = getString(R.string.title_section1);
			break;
		case 2:
			mTitle = getString(R.string.title_section2);
			break;
		case 3:
			mTitle = getString(R.string.title_section3);
			break;
		}
	}

	public void restoreActionBar() {
		ActionBar actionBar = getActionBar();
		actionBar.setNavigationMode(ActionBar.NAVIGATION_MODE_STANDARD);
		actionBar.setDisplayShowTitleEnabled(true);
		actionBar.setTitle(mTitle);
	}

	@Override
	public boolean onCreateOptionsMenu(Menu menu) {
		if (!mNavigationDrawerFragment.isDrawerOpen()) {
			// Only show items in the action bar relevant to this screen
			// if the drawer is not showing. Otherwise, let the drawer
			// decide what to show in the action bar.
			getMenuInflater().inflate(R.menu.main, menu);
			restoreActionBar();
			return true;
		}
		return super.onCreateOptionsMenu(menu);
	}

	@Override
	public boolean onOptionsItemSelected(MenuItem item) {
		// Handle action bar item clicks here. The action bar will
		// automatically handle clicks on the Home/Up button, so long
		// as you specify a parent activity in AndroidManifest.xml.
		int id = item.getItemId();
		if (id == R.id.action_settings) {
			return true;
		}
		return super.onOptionsItemSelected(item);
	}

	// FIXME VRU

	public ArrayAdapter<Group> getAdapter() {
		return adapter;
	}

	/** Called when the user clicks the AddGroup button */
	@SuppressLint("InflateParams")
	public void addGroup(View view) {
		LayoutInflater inflater = getLayoutInflater();
		View groupLayout = inflater.inflate(R.layout.dialog_group, null);
		final EditText groupToAdd = (EditText) groupLayout.findViewById(R.id.dialog_groupToAdd);
		// Build the dialog and set up the button click handlers
		AlertDialog.Builder builder = new AlertDialog.Builder(this);
		builder.setCancelable(true);
		builder.setTitle("Enter the group's name");
		builder.setView(groupLayout);
		DialogInterface.OnClickListener okButton = new DialogInterface.OnClickListener() {
			public void onClick(DialogInterface dialog, int id) {
				dialog.dismiss();
				// Send the positive button event back to the host activity
				String groupName = groupToAdd.getText().toString();
				if (groupName != null && !groupName.equals("")) {
					myGroups.add(new Group(groupName));
					adapter.notifyDataSetChanged();
				} else {
					Toast t = Toast.makeText(getApplicationContext(), "No group added", Toast.LENGTH_SHORT);
					t.show();
				}

			}
		};
		DialogInterface.OnClickListener cancelButton = new DialogInterface.OnClickListener() {
			public void onClick(DialogInterface dialog, int id) {
				dialog.dismiss();
			}
		};
		builder.setPositiveButton("OK", okButton);
		builder.setNegativeButton("CANCEL", cancelButton);
		AlertDialog alert = builder.create();
		alert.show();
	}

	/** Called when the user clicks the RemoveGroup button */
	@SuppressLint("InflateParams")
	public void removeGroup(View view) {
		LayoutInflater inflater = getLayoutInflater();
		View groupLayout = inflater.inflate(R.layout.dialog_remove_group, null);
		final Spinner spinner = (Spinner) groupLayout.findViewById(R.id.dialog_groupToRemove);
		adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
		spinner.setAdapter(adapter);
		final OnSpinnerItemClicked osic = new OnSpinnerItemClicked();
		spinner.setOnItemSelectedListener(osic);

		AlertDialog.Builder builder = new AlertDialog.Builder(this);
		builder.setCancelable(true);
		builder.setTitle("Select group to remove");
		builder.setView(groupLayout);
		builder.setPositiveButton("OK", new DialogInterface.OnClickListener() {
			@Override
			public void onClick(DialogInterface dialog, int which) {
				dialog.dismiss();
				myGroups.remove(osic.getSelectedItem());
				adapter.notifyDataSetChanged();
			}
		});
		builder.setNegativeButton("Cancel", new DialogInterface.OnClickListener() {
			@Override
			public void onClick(DialogInterface dialog, int which) {
				dialog.dismiss();
			}
		});
		AlertDialog alert = builder.create();
		alert.show();

	}

	// FIXME ENDVRU

	/**
	 * A placeholder fragment containing a simple view.
	 */
	public static class PlaceholderFragment extends Fragment {
		/**
		 * The fragment argument representing the section number for this fragment.
		 */
		private static final String ARG_SECTION_NUMBER = "section_number";

		/**
		 * Returns a new instance of this fragment for the given section number.
		 */
		public static PlaceholderFragment newInstance(int sectionNumber) {
			PlaceholderFragment fragment = new PlaceholderFragment();
			Bundle args = new Bundle();
			args.putInt(ARG_SECTION_NUMBER, sectionNumber);
			fragment.setArguments(args);
			return fragment;
		}

		public PlaceholderFragment() {
		}

		@Override
		public View onCreateView(LayoutInflater inflater, ViewGroup container, Bundle savedInstanceState) {
			// FIXME : a rendre propre
			View rootView;
			Bundle args = getArguments();
			int sectionNumber = args.getInt(ARG_SECTION_NUMBER);
			switch (sectionNumber) {
			case 1:
				rootView = inflater.inflate(R.layout.fragment_main, container, false);
				break;
			case 2:
				rootView = inflater.inflate(R.layout.fragment_groups, container, false);
				final ListView groupList = (ListView) rootView.findViewById(R.id.group_listView);
				ArrayAdapter<Group> a = ((MainActivity) getActivity()).getAdapter();
				groupList.setAdapter(a);
				break;
			case 3:
				rootView = inflater.inflate(R.layout.fragment_main, container, false);
				break;
			default:
				rootView = inflater.inflate(R.layout.fragment_main, container, false);
				break;
			}
			return rootView;
		}

		@Override
		public void onAttach(Activity activity) {
			super.onAttach(activity);
			((MainActivity) activity).onSectionAttached(getArguments().getInt(ARG_SECTION_NUMBER));
		}
	}

}
