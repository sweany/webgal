#! /usr/bin/perl -w

# 2003-04-23 - First revision?
# 2004-02-13 - make separate login script for the webgal, use s2 login data
# 2004-12-13 - move configuration into profiles
# 2008-08-14 - added view counting
# 2010-03-14 - fixed for new web host; no longer using showimg.cgi
# 2010-12-13 - begin work to add feature which notifies when images are uploaded to specified directories
# 2011-12-12 - begin new edition - tagging, no page reloads; removing comments for now
#									need tag removal; arbitrary tag search; import tags; duplicate tag checks (replace into?)
# 2012-01-10 - multiple tags can narrow down selection
# 2012-01-18 - can delete images now
# 2013-02-23 - import form gives option to delete duplicates
# 2013-02-24 - image is now clickable; left 1/3rd goes to previous image; right 2/3rds goes to next
# 2013-03-01 - can dynamically add and remove highlighted tags. "Basic Info" replaced with EXIF overlay.

use CGI;
use CGI::Carp qw(fatalsToBrowser warningsToBrowser);
use Digest::MD5;
use Fcntl;
use File::Copy;
use Image::Info;
use Image::Magick;
use Time::Local;
use strict;

use vars qw(%ENV %CONF $dbh $q);

$ENV{PATH} = ''; # untaint the path
$CGI::POST_MAX=10 * 1024 * 1024;  # maximum length of POSTed data
$CGI::DISABLE_UPLOADS = 0;  # no uploads
$| = 1; # hot pipes

my $cmdarg = shift;
$cmdarg = "" unless (defined $cmdarg);
if (lc $cmdarg eq "notify") {
	# find new pictures & generate thumbnails;
	# send new picture notifications; include links to thumbnails in the e-mail message
}

$q = new CGI;

# copy the parameters into a case-insensitive hash
my %p;
foreach ($q->param) {
	my ($u) = uc $_;

	if (defined $p{$u}) {
		$p{$u} .= "\n" . $q->param($_);
	} else {
		$p{$u} = $q->param($_);
	}
}

my $action = $p{'ACTION'};
$action = "" unless (defined $action);
$action = lc $action;

# BUG my $query = $q->query_string;
my $query = $ENV{'QUERY_STRING'};
$query = "" unless (defined $query);
my $method = $q->request_method;
$method = "GET" unless (defined $method);


# configuration defaults
my $localroot = "/var/www/webgal";
my $webroot = "/webgal";
%CONF = (
	'ADMINIP' => '127.0.0.1', # host that is allowed to add tags and upload images
	'ISADMIN' => 0, # do not change from 0
	'LOCALROOT' => $localroot,
	'IMPORTDIR' => "$localroot/import",
	'IMPORTLIMIT' => 50,
	'STOREDIR' => "$localroot/store",
	'WEBROOT' => $webroot,
	'WEBSTORE' => "$webroot/store",
	'SCRIPTURL' => 'https://example.com/webgal/webgal.cgi',
	'HOMEURL' => 'https://example.com/',
	'HOMEDESCR' => 'Pictures',
	'TITLE' => "Web Gallery Deux",
	'COLS' => 5,
	'ROWS' => 5,
	'EXIF' => 1,
	'PROFILEDIR' => "profiles",
	'TNSIZE' => 120,
	'TNQUALITY' => 80,
	'IMAGESIZE' => 900,
	'PROFILE' => 'default',
	'CLR_TEXTBG' => '#444444',
	'CLR_DIRLIST' => '#333333',
	'CLR_IMGBG' => '#333333',
	'CLR_BORDER' => '#222222',
	'CLR_DATE' => '#A0A0A0',
	'CLR_AUTHOR' => '#0088FF',
	'CLR_COMMENT' => '#FFFFFF',
	'PARENTLINK' => 1,
	'DBTYPE' => 'mysql',
	'DBHOST' => 'localhost',
	'DBNAME' => 'webgal2',
	'DBUSER' => 'webgal',
	'DBPASS' => '',
	'COMMENTS' => 0, # enable/disable comments for the galleries
	'COUNT' => 1, # enable/disable counting image views
	'QUERY_STRING' => $query,
	'HTMLSTARTED' => 0, # never change this
);

# load database routines and modules
if ($CONF{'COMMENTS'} or $CONF{'COUNT'}) {
	use DBI;
	do 'sql.pl';
}

# ==============================================================================
# method processing

$CONF{'ISADMIN'} = 1 if $ENV{'REMOTE_ADDR'} eq $CONF{'ADMINIP'};

if ($method eq "GET" or $method eq "POST") {
	my $tags = $p{'TAGS'};
	$tags = 'recent' unless (defined $tags);
        # sanitize tags
        $tags =~ s/[^a-zA-Z0-9_ ]//g;
        $p{'TAGS'} = $tags;
	my $page = $p{'PAGE'};
	my $action = $p{'ACTION'};
	$action = "" unless (defined $action);
	$action = lc $action;
	$tags = "" unless (defined $tags);
	$page = 1 unless (defined $page);
	$tags =~ s/\%20/ /g;
	$tags =~ s/\\/\//g;
	$tags =~ s/\/$//g;

	my $recent = 0;
	if (($tags eq "recent") or ($tags =~ /\s+recent$/i) or ($tags =~ /\s+recent\s+/i) or ($tags =~ /^recent\s+/i)) {
		$recent = 1;
		$tags =~ s/ ?recent ?//ig;
	}

	# get a list of images
	$dbh = DB_Connect($CONF{'DBHOST'},$CONF{'DBNAME'},$CONF{'DBUSER'},$CONF{'DBPASS'});
	my $ref_list;
	my $ref_subtags;
	if ($tags ne "") {
		#$ref_list = DB_GetAll_Ref($dbh,"SELECT num,path,md5,filename,taken,imported FROM images WHERE num = ANY (SELECT image from tags where tag LIKE '%$tags%') ORDER BY taken");
		# split up tags, implicit and
		my @words = split(/ /,$tags);
		my $phrase = "(";
		foreach my $word (@words) {
			next if ($word eq "recent");
			$phrase .= "t.tag LIKE '%" . $word . "%' OR ";
		}
		$phrase =~ s/OR $//;
		$phrase .= ")";
		if (scalar @words == 1) {
			my $strsql = "";
			if ($recent) {
				my $oneweekago = time - 60840000;
				#$strsql = "SELECT i.num,i.path,i.md5,i.filename,i.taken,i.imported FROM images i, tags t WHERE i.num = t.image AND t.tag LIKE '%$tags%' AND i.imported > $oneweekago ORDER BY i.imported DESC, i.taken";
				$strsql = "SELECT i.num,i.path,i.md5,i.filename,i.taken,i.imported FROM images i, tags t WHERE i.num = t.image AND t.tag LIKE '%$tags%' ORDER BY i.imported DESC, i.taken limit 100";
				#print $q->header; print "<br><br>$strsql<br>\n";
			} else {
				$strsql = "SELECT i.num,i.path,i.md5,i.filename,i.taken,i.imported FROM images i, tags t WHERE i.num = t.image AND t.tag LIKE '%$tags%' ORDER BY i.taken, i.imported";
				#print $q->header; print "<br><br>$strsql<br>\n";
			}
			
			$ref_list = DB_GetAll_Ref($dbh,$strsql);
			$strsql = "SELECT DISTINCT tag FROM tags WHERE image = ANY (SELECT image FROM tags WHERE tag LIKE '%$tags%') ORDER BY tag";
			$ref_subtags = DB_GetAll_Ref($dbh, $strsql);
			#print "<br><br>$strsql<br><br>\n";
		} else {
			my $strsql = "";
			if ($recent) {
				my $oneweekago = time - 6084000;
				#$strsql = sprintf("SELECT i.num,i.path,i.md5,i.filename,i.taken,i.imported FROM images i, tags t WHERE i.num = t.image AND i.imported > $oneweekago AND %s group by i.num HAVING (count(i.num) = %d) ORDER BY i.taken, i.imported", $phrase, scalar @words);
				$strsql = sprintf("SELECT i.num,i.path,i.md5,i.filename,i.taken,i.imported FROM images i, tags t WHERE i.num = t.image AND %s group by i.num HAVING (count(i.num) = %d) ORDER BY i.taken, i.imported limit 100", $phrase, scalar @words);
			} else {
				$strsql = sprintf("SELECT i.num,i.path,i.md5,i.filename,i.taken,i.imported FROM images i, tags t WHERE i.num = t.image AND %s group by i.num HAVING (count(i.num) = %d) ORDER BY i.taken, i.imported", $phrase, scalar @words);
			}
			#print "<br><br>\n$strsql<br>\n";
			$ref_list = DB_GetAll_Ref($dbh,$strsql);
			# sub-tags
			#select tag from tags where image = ANY (select image from tags where tag='2011');
			$phrase = "(";
			my $subphrase = "";
				foreach my $word (@words) {
				$phrase .= "tag LIKE '%" . $word . "%' OR ";
				$subphrase .= "image = ANY (SELECT image FROM tags WHERE tag LIKE '%" . $word . "%') AND "; 
			}
			$phrase =~ s/OR $//;
			$phrase .= ")";
			$subphrase =~ s/AND $//;
			#select distinct tag from tags where image = any (select image from tags where tag like '%tree%') and image = any (select image from tags where tag like '%nermal%');  
			$ref_subtags = DB_GetAll_Ref($dbh, "SELECT DISTINCT tag FROM tags WHERE $subphrase ORDER BY tag");
		}
	} else {
		if ($recent) {
			my $oneweekago = time - 6084000;
			#$ref_list = DB_GetAll_Ref($dbh,"SELECT num,path,md5,filename,taken,imported FROM images WHERE imported > $oneweekago ORDER BY imported DESC, taken");
			$ref_list = DB_GetAll_Ref($dbh,"SELECT num,path,md5,filename,taken,imported FROM images ORDER BY taken DESC, taken limit 100");
		} else {
			$ref_list = DB_GetAll_Ref($dbh,"SELECT num,path,md5,filename,taken,imported FROM images ORDER BY taken, imported");
		}
		#$ref_subtags = DB_GetAll_Ref($dbh, "SELECT DISTINCT tag FROM tags ORDER BY tag");
	}

	#%subs = (
	#	'import' => \&action_import,
	#);

	#if (defined $subs{$action}) {
	#	$subs{$action}->(\%p);
	#} else {
	#	exit;
	#}

	if ($action eq "import") {
		# import images from upload directory
		if ($CONF{'ISADMIN'}) {
			print $q->header;
			HTML_Start();
			print "<br><br>\n";
			my $count = importImages(\%p);
			print "\nImport complete. $count new images.<br><br>\n";
		}
	} elsif ($action eq "importform") {
		print $q->header;
		HTML_Start();
		form_Import(\%p);

	} elsif ($action eq "ajax_imageinfo") {
		print $q->header;
		my $num = $p{'FILE'};
		my @imageinfo = DB_GetRow($dbh,"SELECT num,path,md5,filename,taken,imported FROM images WHERE num=$num");
		ajax_imageInfo(\@imageinfo);
} elsif ($action eq "ajax_imagetags") {
		print $q->header;
		my $num = $p{'FILE'};
		my @imageinfo = DB_GetRow($dbh,"SELECT num,path,md5,filename,taken,imported FROM images WHERE num=$num");
		ajax_imageTags(\@imageinfo);

} elsif ($action eq "ajax_highlight") {
		print $q->header;
		ajax_Highlight(\%p) if ($CONF{'ISADMIN'});

} elsif ($action eq "ajax_unhighlight") {
		print $q->header;
		ajax_unHighlight(\%p) if ($CONF{'ISADMIN'});

	} elsif ($action eq "ajax_addtags") {
		print $q->header;
		ajax_addTags(\%p) if ($CONF{'ISADMIN'});

	} elsif ($action eq "ajax_removetag" and $CONF{'ISADMIN'}) {
		print $q->header;
		ajax_removeTag(\%p);

	} elsif ($action eq "ajax_makethumb") {
		print $q->header;
		ajax_makeThumb(\%p);

	} elsif ($action eq "ajax_exif") {
		print $q->header;
		ajax_exif(\%p);

	} elsif ($action eq "showtags") {
		print $q->header;
		HTML_Start();
		drawTags(\%p);	
	} elsif ($action eq "ajax_countview") {
		print $q->header;
		ajax_countView(\%p);
	} elsif ($action eq "uploadform" and $CONF{'ISADMIN'}) {
		print $q->header;
		HTML_Start();
		form_Upload();
	} elsif ($action eq "upload" and $CONF{'ISADMIN'}) {
		print $q->header;
		HTML_Start();
		uploadImages(\%p);
	} elsif ($action eq "delete") {
		print $q->header;
		HTML_Start();
		print "<br><br>\n";
		if ($CONF{'ISADMIN'}) {
			if (defined $p{'IMAGE'}) {
				# delete single image
				my $img = $p{'IMAGE'};
				my ($num,$path,$md5,$filename,$taken,$imported) = DB_GetRow($dbh,"SELECT num,path,md5,filename,taken,imported FROM images WHERE num = $img");
				print "Deleting $filename ($path)<br>\n";
				# delete tag data
				my $strsql = "DELETE FROM tags WHERE image=$num";
				DB_Do($dbh,$strsql);
				# delete exif data
				$strsql = "DELETE FROM exif WHERE image=$num";
				DB_Do($dbh,$strsql);
				# delete view data
				$strsql = "DELETE FROM views WHERE image=$num";
				DB_Do($dbh,$strsql);
				# delete image data
				$strsql = "DELETE FROM images WHERE num=$num";
				DB_Do($dbh,$strsql);
				# delete actual file and thumbnail
				my $subdir = substr($md5,0,2);
				unlink "$CONF{'STOREDIR'}/$path";
				unlink "$CONF{'STOREDIR'}/$subdir/tn_$md5.jpg";
				print "<br>Complete.\n";
				print "<meta HTTP-EQUIV=\"REFRESH\" content=\"2; url=$CONF{SCRIPTURL}?tags=$tags\">\n";
			} else {
				# delete a whole set of images
				for (my $i = 0; $i < scalar @$ref_list; $i++) {
					my $lineref = $ref_list->[$i];
					my ($num,$path,$md5,$filename,$taken,$imported) = @$lineref;
					print "Deleting $filename ($path)<br>\n";
					# delete tag data
					my $strsql = "DELETE FROM tags WHERE image=$num";
					DB_Do($dbh,$strsql);
					# delete exif data
					$strsql = "DELETE FROM exif WHERE image=$num";
					DB_Do($dbh,$strsql);
					# delete view data
					$strsql = "DELETE FROM views WHERE image=$num";
					DB_Do($dbh,$strsql);
					# delete image data
					$strsql = "DELETE FROM images WHERE num=$num";
					DB_Do($dbh,$strsql);
					# delete actual file and thumbnail
					my $subdir = substr($md5,0,2);
					unlink "$CONF{'STOREDIR'}/$path";
					unlink "$CONF{'STOREDIR'}/$subdir/tn_$md5.jpg";
				}
				printf("<br>Complete. Deleted %d images.<br>\n", scalar @$ref_list);
				#print "<meta HTTP-EQUIV=\"REFRESH\" content=\"5; url=$CONF{SCRIPTURL}?tags=$tags\">\n";
			}
		}

	} else {
		# default action
		print $q->header;
		HTML_Start();

		# give the javascript layer data to work with; set the index for the associated arrays if necessary
		print "<script language=\"javascript\">\n";
		my $imagelist = my $pathlist = my $md5list = "";
		my $file = $p{'FILE'}; $file = 0 unless (defined $file);
		my $idx = 0;
		for (my $i = 0; $i < (scalar @$ref_list); $i++) {
			my ($num,$path,$md5,$filename,$taken,$imported) = @{$ref_list->[$i]};
			$idx = $i if ($num eq $file);
			$imagelist .= "$num,";
			$pathlist .= "'$path',";
			$md5list .= "'$md5',";
		}
		$imagelist =~ s/,$//;
		$pathlist =~ s/,$//;
		$md5list =~ s/,$//;
		print "var imageList = [$imagelist];\n";
		print "var pathList = [$pathlist];\n";
		print "var md5List = [$md5list];\n";
		print "var idx = $idx;\n";
		print <<END_HERE;
function toggle_display (id) {
	var o = document.getElementById(id);
	if(o.style.display == 'block') {
		o.style.display = 'none';
	} else {
		o.style.display = 'block';
	}
}

function goPrevious () {
	document.getElementById('loadingtext').style.display = 'block';
	document.getElementById('exifdata').innerHTML = '';
	document.getElementById('exifdata').style.display = 'none';
	document.getElementById('fileinfo').style.display = 'inline';

	//document.getElementById('image').src = '';
	document.getElementById('thumb_previous').src = '';

	document.getElementById('thumb_next').src = '$CONF{WEBSTORE}/'+md5List[idx].substr(0,2)+'/tn_'+md5List[idx]+'.jpg';
	idx -= 1;
	if (idx < 0) {
		idx = imageList.length - 1;
	}
	document.getElementById('filenum').value=imageList[idx];
	document.getElementById('fileinfo').innerHTML='...';
	document.getElementById('image').src = '$CONF{WEBSTORE}/'+pathList[idx];
	document.getElementById('thumb_current').src = '$CONF{WEBSTORE}/'+md5List[idx].substr(0,2)+'/tn_'+md5List[idx]+'.jpg';
	// wrap around to the end if at the beginning
	if (idx == 0) {
		document.getElementById('thumb_previous').src = '$CONF{WEBSTORE}/'+md5List[imageList.length-1].substr(0,2)+'/tn_'+md5List[imageList.length-1]+'.jpg';
	} else {
		document.getElementById('thumb_previous').src = '$CONF{WEBSTORE}/'+md5List[idx-1].substr(0,2)+'/tn_'+md5List[idx-1]+'.jpg';
	}
	document.getElementById('fileinfo').innerHTML=webGet('$CONF{SCRIPTURL}?action=ajax_imagetags&file='+imageList[idx]);
	document.getElementById('exifoverlay').innerHTML=webGet('$CONF{SCRIPTURL}?action=ajax_imageinfo&file='+imageList[idx]);


	var displaynum = idx + 1;
	document.getElementById('imagenum').innerHTML='image ' + displaynum + ' of ' + imageList.length;

	// update the delete link
	if (document.getElementById('link_delete')) {
		document.getElementById('link_delete').innerHTML = '<a onclick=\"if(confirm(\\\'Delete this image?\\\')){ window.location=\\\'$CONF{SCRIPTURL}?action=delete&image=\\\'+imageList[idx]; }\" style=\"color:red; cursor:pointer;\">Delete this image</a>';
	}
	document.getElementById('loadingtext').style.display = 'none';

	// count the image view
	webGet('$CONF{SCRIPTURL}?action=ajax_countview&file='+imageList[idx]);
}

function goNext () {
	document.getElementById('loadingtext').style.display = 'block';
	document.getElementById('exifdata').innerHTML = '';
	document.getElementById('exifdata').style.display = 'none';
	document.getElementById('fileinfo').style.display = 'inline';

	//document.getElementById('image').src = '';
	document.getElementById('thumb_next').src = '';

	document.getElementById('thumb_previous').src = '$CONF{WEBSTORE}/'+md5List[idx].substr(0,2)+'/tn_'+md5List[idx]+'.jpg';
	idx += 1;
	if (idx > (imageList.length-1)) {
		idx = 0;
	}
	document.getElementById('filenum').value=imageList[idx];
	document.getElementById('fileinfo').innerHTML='...';
	document.getElementById('image').src = '$CONF{WEBSTORE}/'+pathList[idx];
	document.getElementById('thumb_current').src = '$CONF{WEBSTORE}/'+md5List[idx].substr(0,2)+'/tn_'+md5List[idx]+'.jpg';
	// wrap around to the beginning if at the end
	if (idx == (imageList.length-1)) {
		document.getElementById('thumb_next').src = '$CONF{WEBSTORE}/'+md5List[0].substr(0,2)+'/tn_'+md5List[0]+'.jpg';
	} else {
		document.getElementById('thumb_next').src = '$CONF{WEBSTORE}/'+md5List[idx+1].substr(0,2)+'/tn_'+md5List[idx+1]+'.jpg';
	}
	document.getElementById('fileinfo').innerHTML=webGet('$CONF{SCRIPTURL}?action=ajax_imagetags&file='+imageList[idx]);
	document.getElementById('exifoverlay').innerHTML=webGet('$CONF{SCRIPTURL}?action=ajax_imageinfo&file='+imageList[idx]);

	var displaynum = idx + 1;
	document.getElementById('imagenum').innerHTML='image ' + displaynum + ' of ' + imageList.length;

	// update the delete link
	if (document.getElementById('link_delete')) {
		document.getElementById('link_delete').innerHTML = '<a onclick=\"if(confirm(\\\'Delete this image?\\\')){ window.location=\\\'$CONF{SCRIPTURL}?action=delete&image=\\\'+imageList[idx]; }\" style=\"color:red; cursor:pointer;\">Delete this image</a>';
	}
	document.getElementById('loadingtext').style.display = 'none';
	// count the image view
	webGet('$CONF{SCRIPTURL}?action=ajax_countview&file='+imageList[idx]);
}

var displaynum = idx + 1;
setTimeout("document.getElementById('imagenum').innerHTML='image ' + displaynum + ' of ' + imageList.length", 1000);

END_HERE
		print "</script>\n";

		if (defined $p{'FILE'}) { # display a specific image
			my $num = $p{'FILE'};
			my @imageinfo = DB_GetRow($dbh,"SELECT num,path,md5,filename,taken,imported FROM images WHERE num=$num");
			if (defined $imageinfo[0]) {
				drawPage_image(\%p,\@imageinfo,$ref_list);
			} else {
				print "<br>Image not found.<br>\n";
			}
		} else { # display an index of images
			drawPage_index(\%p,$ref_list,$ref_subtags);
		}
		print "</body></html>\n";
	}
}

$dbh->disconnect;
exit;





################################################################################


sub catTemplate {
	my $filename = shift;
	$filename = "" unless (defined $filename);
	my $filetext = "";

	die "catTemplate(): Could not open $filename: $!" unless (sysopen(FILE, $filename, O_RDONLY));
	while (<FILE>) {
		$filetext .= $_;
	}
	close (FILE);
	return $filetext;
}

sub fillTemplate {
	my ($text,@p) = @_;
	return "" unless (defined $text);

	for (my $i = 0; $i <= $#p; $i += 2) {
		my ($field, $value) = ($p[$i],$p[$i+1]);
		if (defined $value) {
			$text =~ s/\{\{$field\}\}/$value/g;
		} else {
			$text =~ s/\{\{$field\}\}/\[ undefined: $field \]/g;
		}
	}
	# replace any remaining placeholders
	$text =~ s/\{\{.*\}\}/\<font color=\"#0066CC\"\>\?\?\?\<\/font\>/g;
	return $text;
}

sub exifInfo {
	my $infile = shift;

	# exifTool version
	use Image::ExifTool 'ImageInfo';

	my $exif = ImageInfo($infile);
	#while (my ($name,$value) = each %$exif) {
	#	print "$name = $value<br>\n";
	#}

	my $model = $exif->{Model};
	$model = "" unless (defined $model);
	my $aperture;
	$aperture = "f/" . eval ($exif->{FNumber}) if (defined $exif->{FNumber});
	$aperture = "f/" . eval ($exif->{Aperture}) if ( (! defined $aperture) and (defined $exif->{Aperture}) );
	$aperture = "?" unless (defined $aperture);
	my $exposure;
	$exposure = $exif->{ExposureTime} if (defined $exif->{ExposureTime});
	#$exposure = sprintf("%.3f", eval ($exif->{ExposureTime})) if (defined $exif->{ExposureTime});
	$exposure = $exif->{ShutterSpeed} if ( (! defined $exposure) and (defined $exif->{ShutterSpeed}) );
	#$exposure = sprintf("%.3f", eval ($exif->{ShutterSpeed})) if ( (! defined $exposure) and (defined $exif->{ShutterSpeed}) );
	$exposure = "?" unless (defined $exposure);
	my $stamp = $exif->{DateTimeOriginal};
	$stamp = "" unless (defined $stamp);
	my $speed = $exif->{ISOSpeedRatings};
	$speed = $exif->{ISO} unless (defined $speed);
	$speed = "" unless (defined $speed);
	my $date = "";
	my $time = "";
	if ($stamp ne "") {
		($date,$time) = split(/ /,$stamp);
		$date =~ s/\:/\-/g;
	}
	my $focal;
	$focal = $exif->{FocalLength} if (defined $exif->{FocalLength});
	$focal = "?" unless (defined $focal);

	return ($date,$time,$aperture,$exposure,$speed,$focal,$model);
}

sub HTML_Start {
	my $title = $CONF{'TITLE'};

	$CONF{'HTMLSTARTED'} = 1;
	print "<!DOCTYPE html><html>\n";
	print "<head>\n";
	print "<title>$title</title>\n";
	print "<link rel=\"stylesheet\" href=\"$CONF{PROFILEDIR}/$CONF{PROFILE}/webgal.css\" type=\"text/css\">\n";
	print "</head>\n";
	print <<END_HERE;
<script language="javascript">
function webGet (url) {
        if (window.XMLHttpRequest) {
                var req = new XMLHttpRequest();
                req.open("GET", url, false);
                req.send("");
                return req.responseText;
        } else if (window.ActiveXObject) {
                var req = new ActiveXObject("Microsoft.XMLHTTP");
                if (req) {
                        req.open("GET", url, false);
                        req.send();
                }
                return req.responseText;
        }

}
</script>

END_HERE
	# google analytics code
	unless ($CONF{'QUERY_STRING'} =~ /\.tmp/) {
		#print "<script type=\"text/javascript\">\n";
		#print "var _gaq = _gaq || []; _gaq.push(['_setAccount', 'UA-172038-4']); _gaq.push(['_trackPageview']);\n";
		#print "(function() { var ga = document.createElement('script'); ga.type = 'text/javascript'; ga.async = true; ga.src = ('https:' == document.location.protocol ? 'https://ssl' : 'http://www') + '.google-analytics.com/ga.js'; var s = document.getElementsByTagName('script')[0]; s.parentNode.insertBefore(ga, s);  })();\n";
		#print "</script>\n";
	}
	print "<br>\n";
	drawToolbar();
}

sub parentDir {
	my $dir = shift;
	my $count = shift;
	my @tmp = split(/\//,$dir);

	for (1..$count) {
		my $crap = pop @tmp;
	}
	return join("/",@tmp);
}

sub getImageSize {
	my $infile = shift;
	my $img = Image::Magick->new();
	my ($width, $height, $size, $format) = $img->Ping($infile); 
	$width = 1 unless (defined $width);
	$height = 1 unless (defined $height);
	return ($width,$height);
}

sub resize {
	my $infile = shift;
	my $outfile = shift;
	my $width = shift;
	my $height = shift;

	my $thumbnail = 0;
	$thumbnail = 1 if ($width <= $CONF{'TNSIZE'});

	my $size = $width . "x" . $height;

	my $image = Image::Magick->new();
	my $result = $image->Read($infile);
	if ($result ne "") {
		print "While reading $infile: '$result'\n";
		return 0;
	}

	my $filesize = $image->Get("filesize");
	$filesize = int($filesize / 1024);
	my $w = $image->Get("width");
	my $h = $image->Get("height");
	
	$result = $image->Resize(geometry => $size, filter => 'Box', blur => 1);
	if ($result ne "") {
		print "While resizing $infile: '$result'\n";
	}

	if ($thumbnail) {
		$result = $image->Crop(geometry => "80x80+0+0", gravity => 'Center');
		warn $result if ($result);

		$image->Profile('*') if ($thumbnail); # VERY IMPORTANT FOR THUMBNAILS

		$result = $image->Write(filename => $outfile, quality => $CONF{'TNQUALITY'});
	} else {
		$result = $image->Write(filename => $outfile, quality => 85);
	}

	if ($result ne "") {
		print "While writing $infile: '$result'\n";
	}

	undef $image;
}

sub md5 {
	my $file = shift;
	return 0 unless (-f $file);
	open(FILE, $file) or return "0";
	binmode(FILE);
	return Digest::MD5->new->addfile(*FILE)->hexdigest;
	close (FILE);
}


sub shortLocalTime {
	my $date = shift;
	$date = 0 unless (defined $date);
	my %months = ('Jan' => 1, 'Feb' => 2, 'Mar' => 3, 'Apr' => 4,
		'May', => 5, 'Jun' => 6, 'Jul' => 7, 'Aug' => 8,
		'Sep' => 9, 'Oct' => 10, 'Nov' => 11, 'Dec' => 12);
	$date = localtime($date);
	if ($date =~ /\w+ (\w+) +(\d+) (\d\d):(\d\d):\d\d (\d\d\d\d)/) {
		my $month = $months{$1};
		my $day = $2;
		$day = "0$day" if ($day < 10);
		$month = "0$month" if ($month < 10);
		return "$5-$month-$day $3:$4";
	} else {
		return "???";
	}
}


sub drawPage_index { # draw thumbnails for all images with the specified tags
	my $p = shift;
	my $ref = shift;
	my $ref_subtags = shift;

	my $page = $p->{'PAGE'};
	my $tags = $p->{'TAGS'};
	$tags = "" unless (defined $tags);

	print "<div style=\"position:relative; left:25px; top:25px;\">\n"; # containing block

	print "<div style=\"float:left; position:relative; margin-right:10px; z-index:50;\">\n";
	drawHighlights();
	print "</div>\n";

	print "<div style=\"position:relative;\">\n";
	my @words = split(/ /,$tags);
	my $current_tags = "";
	for (my $i = 0; $i <= $#words; $i++) {
		my $word = $words[$i];
		my $stripped = $tags;
		$stripped =~ s/$word//ig;
		$stripped =~ s/ $//;
		$stripped =~ s/^ //;
		$stripped =~ s/  / /g;
		my $xlink = $CONF{'SCRIPTURL'} . "?tags=$stripped";
		$current_tags .= "$word <a href=\"$xlink\" style=\"color: red;\">x</a>, ";
	}
	$current_tags = "(none)" if ($current_tags eq "");
	print "Current tags: $current_tags<br><br>\n";

	print "<table>\n<tr>\n";
	my $colnum = 0;
	my $rows = 0;
	$page = 1 unless (defined $page);
	$page = 1 if ($page == 0);
	#my $skip = (($CONF{'ROWS'} * $CONF{'COLS'}) * ($page-1)) + 1;
	my $skip = (($CONF{'ROWS'} * $CONF{'COLS'}) * ($page-1));
	$skip = 0 unless (defined $skip);
	my $width = int($CONF{'TNSIZE'}*.6666) + 1;
	my $height = int($CONF{'TNSIZE'}*.6666) + 1;
	for (my $i = $skip; $i < (scalar @$ref); $i++) {
		my $lineref = $ref->[$i];
		my ($num,$path,$md5,$filename,$taken,$imported) = @$lineref;
		#print "$num $path $md5<br>\n";

		#my $md5_verify = md5("$localroot/$path");
		# do the hashes match?
		# do some error checking here
		my $subdir = substr($md5,0,2);
		my $thumb = "tn_$md5.jpg";

		# does the thumbnail exist?
		if (! (-f "$CONF{STOREDIR}/$subdir/$thumb")) {
			# create the thumbnail
			#print STDERR "Creating thumbnail for $file, $md5\n";
			resize("$CONF{STOREDIR}/$path","$CONF{STOREDIR}/$subdir/$thumb",$CONF{'TNSIZE'},$CONF{'TNSIZE'});
		}

		# display the thumbnail
		my $linkurl = $CONF{'SCRIPTURL'} . "?file=$num&tags=$tags";
		my $thumburl = $CONF{'WEBSTORE'} . "/$subdir/$thumb";
		my ($tn_w,$tn_h) = getImageSize("$CONF{STOREDIR}/$subdir/$thumb"); # HTML renders better if we know the image size in advance
		print "<td align=\"center\" width=\"$width\" height=\"$height\" padding=\"1\"><a href=\"$linkurl\"><img src=\"$thumburl\" border=\"0\" alt=\"thumbnail\" width=\"$tn_w\" height=\"$tn_h\"></a></td>\n";
		#print "<br><font class=\"tiny\">$file</font></td>\n";

		$colnum += 1;
		if ($colnum >= $CONF{'COLS'}) {
			print "</tr>\n";
			$rows += 1;
			last if ($rows == $CONF{'ROWS'});
			#print "<tr><td>&nbsp;</td></tr\n";
			print "<tr>\n";
			$colnum = 0;
		}
	}
	print "</tr>\n<tr><td colspan=\"10\">\n";

	# calculate last page
	my $lastpage = scalar @$ref / ($CONF{'ROWS'} * $CONF{'COLS'});
	if ($lastpage - int($lastpage) > 0) {
		$lastpage = int($lastpage) + 1;
	} else {
		$lastpage = int($lastpage);
	}

	#
	# print page navigation
	print "<span class=\"small\">";
	if ($page > 1) {
		my $prevpage = $page - 1;
		print "<a href=\"$CONF{SCRIPTURL}?tags=$tags&amp;page=$prevpage\">Prev</a>&nbsp;";
	} else {
		print "Prev&nbsp;";
	}
	print "<select id=\"pagenum\" onchange=\"location='$CONF{SCRIPTURL}?tags=$tags&amp;page='+this.value\">\n";
	for (my $i = 1; $i <= $lastpage; $i++) {
		if ($i == $page) {
			print "<option value=\"$i\" selected>page $i of $lastpage</option>\n";
			#print "<b>_$i\_</b>&nbsp;";
		} else {
			print "<option value=\"$i\">$i</option>\n";
			#print "<a href=\"$CONF{SCRIPTURL}?tags=$tags&amp;page=$i\">$i</a>&nbsp;";
		}
	}
	print "</select>\n";
	if ($page < $lastpage) {
		my $nextpage = $page + 1;
		print "<a href=\"$CONF{SCRIPTURL}?tags=$tags&amp;page=$nextpage\">Next</a>&nbsp;";
	} else {
		print "Next&nbsp;";
	}
	print "</span>\n";
	printf(" &nbsp; %d images.", scalar @$ref);
	print " &nbsp; <a onclick=\"if(confirm('Delete all images in this set?')){ window.location='$CONF{SCRIPTURL}?action=delete&tags=$tags'; }\" style=\"color:red; cursor:pointer;\">Delete these images</a><br>\n" if ($CONF{'ISADMIN'});
	print "</td></tr></table>\n";
	
	print "</div>\n";
	
	print "<div style=\"position:relative; top:25px; width:720px;\">\n";
	
	if (defined $ref_subtags) {
		print "Narrow down your selection: <br>";
		#print @$ref_subtags;
		for (my $i = 0; $i < (scalar @$ref_subtags); $i++) {
			my $tag = $ref_subtags->[$i][0];
			printf("<a href=\"%s\">%s</a>, \n", "$CONF{SCRIPTURL}?tags=$tags $tag", $tag);
		}
		print "<br><br>\n";
	}
	
	print "</div>\n"; 
	print "</div>\n"; # end containing block
	
}

sub drawHighlights {
	# print highlighted tags
	my $strsql = "SELECT value FROM configuration WHERE name='highlight' ORDER BY value";
	my $ref_highlights = DB_GetAll_Ref($dbh,$strsql);
	print "Highlighted tags:<br><br>\n";
	for (my $i = 0; $i < (scalar @$ref_highlights); $i++) {
		my $highlight = $ref_highlights->[$i][0];
		print "<a href=\"$CONF{SCRIPTURL}?tags=$highlight\">$highlight</a>";
		print " &nbsp; <a onclick=\"if(confirm('Un-highlight the $highlight tag?')){ webGet('$CONF{SCRIPTURL}?action=ajax_unhighlight&highlight=$highlight'); document.location='$CONF{SCRIPTURL}'; }\" style=\"color:red; cursor:pointer;\">x</a>" if ($CONF{'ISADMIN'});
		print "<br>\n";
	}
	# form for adding highlighted tags
	if ($CONF{'ISADMIN'}) {
		print "<span class=\"small\"><form id=\"highlightform\" onsubmit=\"var highlight = document.getElementById('highlight').value; webGet('$CONF{SCRIPTURL}?action=ajax_highlight&highlight='+highlight); document.getElementById('highlight').value=''; document.location='$CONF{SCRIPTURL}';\"><input id=\"highlight\" name=\"highlight\" size=\"12\" type=\"text\"></form></span><br>\n";
	}

}

sub drawPage_image {
	my $p = shift;
	my $ref_image = shift; # image information
	my $images = shift; # the whole list of images in this group
	my $tags = $p->{'TAGS'};

	my ($num,$path,$md5,$filename,$taken,$imported) = @$ref_image;
	my $filelist = ""; # to allow javascript to keep track of all the images
	my $file = $path; # temporary hack 2011-12-12 13:56:09
	my $dir = ""; # same as above

	# find out which file this is in the sequence so we can link to the previous and next
	my $ref_previous;
	my $ref_next;
	my $parentpage = 1;
	my $lastimg = (scalar @$images) - 1;

	for (my $i = 0; $i <= $lastimg; $i++) {
		$filelist .= $images->[$i][0] . " ";
		my ($n,$p,$m,$d) = @{$images->[$i]};
		if ($path eq $p) {
			if ($i == 0) {
				$ref_previous = $images->[$lastimg];
				$ref_next = $images->[$i + 1];
			} elsif ($i == $lastimg) {
				$ref_previous = $images->[$i - 1];
				$ref_next = $images->[0];
			} else {
				$ref_previous = $images->[$i - 1];
				$ref_next = $images->[$i + 1];
			}

			# which index page is this image on?
			if (! ($i % ($CONF{'ROWS'} * $CONF{'COLS'})) ) {
				$parentpage = int($i / ($CONF{'ROWS'} * $CONF{'COLS'}));
			} else {
				$parentpage = int($i / ($CONF{'ROWS'} * $CONF{'COLS'})) + 1;
			}		
			last;
		}
	}
	my $next = $ref_next->[0];
	my $next_path = $ref_next->[1];
	my $previous = $ref_previous->[0];
	my $previous_path = $ref_previous->[1];

	my $fileinfo = return_fileInfo($num,$path,$filename);
	my $taglinks = return_tagLinks($num,$path,$filename);

	#my $boxsize = 0;
	my ($w,$h) = getImageSize("$CONF{STOREDIR}/$path");
	#if ($w > $h) {
	#	$boxsize = $w;
	#} else {
	#	$boxsize = $h;
	#}
	my $boxsize = $CONF{'IMAGESIZE'};

	my $md5_previous = md5("$CONF{STOREDIR}/$previous_path");
	my $md5_current = md5("$CONF{STOREDIR}/$path");
	my $md5_next = md5("$CONF{STOREDIR}/$next_path");
	
	my $thumb_previous = sprintf("%s/tn_%s.jpg", substr($md5_previous,0,2), $md5_previous);
	my $thumb_current = sprintf("%s/tn_%s.jpg", substr($md5_current,0,2), $md5_current);
	my $thumb_next = sprintf("%s/tn_%s.jpg", substr($md5_next,0,2), $md5_next);

	# if one of the thumbs does not exist, create it
	#resize("$CONF{STOREDIR}/$previous","$CONF{STOREDIR}/tn_$md5_previous.jpg",$CONF{'TNSIZE'},$CONF{'TNSIZE'}) if (! (-f "$CONF{STOREDIR}/tn_$md5_previous.jpg"));
	#resize("$CONF{STOREDIR}/$path","$CONF{STOREDIR}/tn_$md5_current.jpg",$CONF{'TNSIZE'},$CONF{'TNSIZE'}) 	if (! (-f "$CONF{STOREDIR}/tn_$md5_current.jpg"));
	#resize("$CONF{STOREDIR}/$next","$CONF{STOREDIR}/tn_$md5_next.jpg",$CONF{'TNSIZE'},$CONF{'TNSIZE'}) 	if (! (-f "$CONF{STOREDIR}/tn_$md5_next.jpg"));

	# draw the page
	print "<div style=\"position:relative; left:25px; top:25px;\">\n"; # containing block

	# image and info
	print "<div style=\"position:relative; float:left; width:$boxsize" . "px; padding:2px; border-style:solid; border-width:1px; border-color:$CONF{CLR_BORDER}; background-color:$CONF{CLR_IMGBG};\">\n";
	print "<div id=\"loadingtext\" style=\"position:absolute; top:0; display:none; opacity:0.7; width:100%; height:100%; z-index:5;\"><span style=\"font-size:36px; text-align:center; text-shadow:2px 2px 2px #000;\"><br><br><br><br><center>Loading...</center></span></div>\n";
	print "<div id=\"exifoverlay\" style=\"position:absolute; bottom:0; padding:5px; display:none; background-color:#000000; opacity:0.7; z-index:5;\">$fileinfo</div>\n";
	#print "<div id=\"headerprevious\" style=\"position:absolute; left:0; padding:0px; width:" . int($boxsize/3) . "px; height:15px; background-color:#663333\"> <div style=\"padding-bottom:2px;\">Previous</div></div>\n";
	#print "<div id=\"headernext\" style=\"position:absolute; right:0; padding:0px; width:" . int(($boxsize/3)*2) . "px; height:15px; background-color:#333366\"> <div style=\"padding-bottom:2px;\">Next</div></div>\n";
	print "<div id=\"clickleft\" style=\"position:absolute; left:0; width:" . int($boxsize/3) . "px; height:100%; z-index:10;\"><a href=\"#\" onclick=\"goPrevious();\" style=\"cursor:pointer; display:block; width:100%; height:100%\"></a></div>\n";
	print "<div id=\"clickright\" style=\"position:absolute; right:0; width:" . int(($boxsize/3)*2) . "px; height:100%; z-index:10;\"><a href=\"#\" onclick=\"goNext();\" style=\"cursor:pointer; display:block; width:100%; height:100%\"></a></div>\n";
	print "<center>\n";
	#print "<div id=\"mainimage\" style=\"position:relative; margin:auto;\"><a href=\"$CONF{SCRIPTURL}?tags=$tags&amp;page=$parentpage\"><img src=\"$CONF{WEBSTORE}/$path\" id=\"image\" border=\"0\" style=\"color: white\" alt=\"$file\"></a></div>\n";
	print "<div id=\"mainimage\" style=\"position:relative; margin:auto;\"><a href=\"#\" onclick=\"goNext();\" style=\"cursor:pointer;\"><img src=\"$CONF{WEBSTORE}/$path\" id=\"image\" border=\"0\" style=\"color: white\" alt=\"$file\"></a></div>\n";
	print "</center>\n";
	print "</div>\n";

	print "<div style=\"position:relative;\">\n"; # thumbnail div
	# previous thumbnail
	print "<a onclick=\"goPrevious();\" style=\"cursor:pointer;\"><img src=\"$CONF{WEBSTORE}/$thumb_previous\" id=\"thumb_previous\" alt=\"Previous image\" border=\"0\"></a>\n";
	# current thumbnail
	print "<img src=\"$CONF{WEBSTORE}/$thumb_current\" id=\"thumb_current\" alt=\"Current image\" border=\"1\"></a>\n";
	# next thumbnail
	print "<a onclick=\"goNext();\" style=\"cursor:pointer;\"><img src=\"$CONF{WEBSTORE}/$thumb_next\" id=\"thumb_next\" alt=\"Next image\" border=\"0\"></a>\n";
	print "<br><div id=\"imagenum\"></div>\n"; # image number
	print "</div>\n"; # end thumbnail div

	print "<div style=\"position:relative; float:left; width:320px; height:200px; top:25px;\">\n";
	# info menu
	#print "<div style=\"display:inline; background-color: black; padding:2px;\"><b><a onclick=\"document.getElementById('fileinfo').style.display='inline'; document.getElementById('exifdata').style.display='none';\" style=\"cursor:pointer; color:orange;\">Basic</a> | <a onclick=\"document.getElementById('fileinfo').style.display='none'; document.getElementById('exifdata').style.display='inline'; document.getElementById('exifdata').innerHTML=webGet('$CONF{SCRIPTURL}?action=ajax_exif&file='+imageList[idx]);\" style=\"cursor:pointer; color:orange;\">EXIF</a></b></div><br>\n";
	print "<div style=\"display:inline; background-color: black; padding:2px;\"> <b><a onclick=\"toggle_display('exifoverlay');\" style=\"cursor:pointer\">EXIF Overlay</a></b> </div><br>\n";
	# basic file info
	print "<div id=\"fileinfo\" class=\"small\" style=\"width:32em; display:inline; height:10em;\">$taglinks</div>\n";
	print "<textarea id=\"exifdata\" rows=\"10\" cols=\"40\" style=\"width:40em; height:10em; display:none;\"></textarea>\n";
	# exif data
	if ($CONF{'ISADMIN'}) {
		print "<span class=\"small\"><form id=\"tagform\" onsubmit=\"var curfile = document.getElementById('filenum').value; webGet('$CONF{SCRIPTURL}?action=ajax_addtags&file='+curfile+'&tags='+document.getElementById('taginput').value); document.getElementById('taginput').value=''; document.getElementById('fileinfo').innerHTML=webGet('$CONF{SCRIPTURL}?action=ajax_imagetags&file='+curfile); return false;\"><input id=\"taginput\" name=\"taginput\" size=\"40\" type=\"text\"></form></span><br>\n";
		print "<div id=\"link_delete\"><a onclick=\"if(confirm('Delete this image?')){ window.location='$CONF{SCRIPTURL}?action=delete&image=$num'; }\" style=\"color:red; cursor:pointer;\">Delete this image</a></div>\n"
	}
	print "<br>";
	print "</div>\n";

	print "</div>\n";
	# hidden input fields for tracking what is currently displayed; necessary for ajax continuity
	for (my $i = 0; $i <= $lastimg; $i++) {
		$filelist .= $images->[$i][0] . " ";
	}
	print "<input id=\"filenum\" type=\"hidden\" value=\"$num\">\n";

	countView($num);
	# debug input fields
#print <<END_HERE;
#<input id=\"debug_idx\" type=\"text\" size=\"10\">
#<input id=\"debug_path\" type=\"text\" size=\"20\">
#<input id=\"debug_md5\" type=\"text\" size=\"20\">
#<input id=\"debug_msg\" type=\"text\" size=\"80\">
#<script language=\"javascript\">
#	setInterval("document.getElementById('debug_idx').value='idx: '+idx", 1000);
#	setInterval("document.getElementById('debug_path').value=pathList[idx]", 1000);
#	setInterval("document.getElementById('debug_md5').value=md5List[idx]", 1000);
#	//setInterval("document.getElementById('debug_msg').value=msg", 1000);
#</script>
#END_HERE
	print "</div>\n"; # end containing block
}

sub countView {
	my $file = shift;
	my $now = time;
	my $ipaddr = $ENV{'REMOTE_ADDR'};
	my $ua = $ENV{'HTTP_USER_AGENT'};
	DB_Do($dbh,"INSERT INTO views (image,stamp,ipaddr,useragent) VALUES ($file,$now,'$ipaddr','$ua')");
	DB_Do($dbh,"UPDATE images SET views=views+1 WHERE num=$file");
	return 1;
}

sub uploadImages {
	my $p = shift;
	my $file = $p->{'IMAGEFILE'};
	my $tag = $p->{'TAG'}; $tag = "" unless (defined $tag);

	print "<br><br>import '$file'<br><br>\n";

	my $hash = $q->uploadInfo($file);
	my $disposition = $q->uploadInfo($file)->{'Content-Disposition'};
	$disposition =~ /filename=\"([^\"]+)\"/;
	my $filename_original = $1;
 	unless (defined $filename_original) {
 		$filename_original = $file;
 	}
	$filename_original =~ s/\\/\//g;
	if ($filename_original =~ /\//) {
		$filename_original = substr($filename_original,rindex("/",$filename_original));
	}

	my $type = $hash->{'Content-Type'};
	unless ($type =~ /^image\/jpeg/) {
		die "Can only upload jpeg images, not any other file type ($type)";
	}

	# perform the upload; write to import directory
	unless (sysopen(OUTFILE,"$CONF{IMPORTDIR}/$filename_original",O_WRONLY|O_CREAT|O_TRUNC)) {
		die "Cannot write to $CONF{IMPORTDIR}/$filename_original : $!";
	}
	binmode OUTFILE;
	while (<$file>) {
		print OUTFILE $_;
	}
	close (OUTFILE);

	# shrink large images
	my ($w,$h) = getImageSize("$CONF{IMPORTDIR}/$filename_original");
	if (($w > $CONF{IMAGESIZE}) or ($h > $CONF{'IMAGESIZE'})) {
		print "Resizing $filename_original ($w x $h) ...<br>\n";
		resize("$CONF{IMPORTDIR}/$filename_original","$CONF{IMPORTDIR}/$filename_original.tmp",$CONF{'IMAGESIZE'},$CONF{'IMAGESIZE'});
		rename "$CONF{IMPORTDIR}/$filename_original", "$CONF{IMPORTDIR}/$filename_original.orig";
		rename "$CONF{IMPORTDIR}/$filename_original.tmp", "$CONF{IMPORTDIR}/$filename_original";
		}

	importFile($p, $filename_original, $tag);

	print "$filename_original imported.<br>\n";
	exit;
	return 1;
}


sub importImages {
	my $p = shift;
	my $tag = $p->{'TAG'};
	$tag = "" unless (defined $tag);

	use Image::ExifTool 'ImageInfo';

	#print "importing images...<br>\n";
	my ($sec,$min,$hour,$mday,$mon,$year,$wday,$yday,$isdst) = localtime();
	my $today = sprintf("%4d-%02d-%02d", $year + 1900, $mon + 1, $mday);
	#print "Creating $CONF{STOREDIR}/$today<br>\n";
	opendir(DIR,$CONF{'IMPORTDIR'}) or warn "Could not open import directory: $!";
	my $count = 0;
	while (my $file = readdir(DIR)) {
		next if ($file =~ /^\./);
		next unless ($file =~ /\.jpg$/i); # only import images!

		# shrink large images
		my ($w,$h) = getImageSize("$CONF{IMPORTDIR}/$file");
		if (($w > $CONF{IMAGESIZE}) or ($h > $CONF{'IMAGESIZE'})) {
			print "Resizing $file ($w x $h) ...<br>\n";
			resize("$CONF{IMPORTDIR}/$file","$CONF{IMPORTDIR}/$file.tmp",$CONF{'IMAGESIZE'},$CONF{'IMAGESIZE'});
			rename "$CONF{IMPORTDIR}/$file", "$CONF{IMPORTDIR}/$file.orig";
			rename "$CONF{IMPORTDIR}/$file.tmp", "$CONF{IMPORTDIR}/$file";
		}
		
		importFile($p, $file, $tag);

		$count += 1;
		last if ($count == $CONF{'IMPORTLIMIT'});
	}
	closedir(DIR);
	return $count;
}

sub importFile {
		my $p = shift;
		my $file = shift; # expecting only a filename, not full path
		my $tag = shift;

		my $md5 = md5("$CONF{IMPORTDIR}/$file");
		# delete if this is a duplicate image
		my ($duplicate) = DB_GetRow($dbh, "SELECT Count(1) FROM images WHERE md5='$md5'");
		if ($duplicate) {
			print "$file is a duplicate, purging from import directory<br>\n";
			unlink "$CONF{IMPORTDIR}/$file" or warn "unable to delete $file: $!";
			return 0;
		}
		my $subdir = substr($md5,0,2);
		mkdir "$CONF{STOREDIR}/$subdir" unless (-d "$CONF{STOREDIR}/$subdir");
		my $path = "$subdir/$md5.jpg";
		my $now = time;

		# create thumbnail if it doesn't already exist
		resize("$CONF{IMPORTDIR}/$file","$CONF{STOREDIR}/$subdir/tn_$md5.jpg",$CONF{'TNSIZE'},$CONF{'TNSIZE'}) if (! (-f "$CONF{STOREDIR}/$subdir/tn_$md5.jpg"));

		print "$file => $path<br>\n";
		rename "$CONF{IMPORTDIR}/$file", "$CONF{STOREDIR}/$path" or warn "Could not move $file: $!";
		my ($date,$time,$aperture,$exposure,$speed,$focal,$model) = exifInfo("$CONF{STOREDIR}/$path");
		my ($year,$mon,$mday) = split(/-/,$date);
		my ($hour,$min,$sec) = split(/:/,$time);
		$focal =~ s/ mm//;
		$focal = sprintf("%d", $focal);
		my $exposure_integer = $exposure;
		if ($exposure =~ /\//) {
			my (undef,$fraction) = split(/\//,$exposure);
			$exposure_integer = 1 / $fraction;
		}
		my $taken = $now; # default value if import time if it isn't in the exif data; should probably change this to file modification time
		eval { $taken = timelocal($sec,$min,$hour,$mday,$mon-1,$year); };
		my (undef,undef,undef,undef,undef,undef,$wday,$yday,$isdst) = localtime($taken);

		my $strsql = "INSERT INTO images (path, md5, filename, taken, imported) VALUES ('$path', '$md5', '$file', $taken, $now)";
		DB_Do($dbh,$strsql);
		my ($num) = DB_GetRow($dbh, "SELECT LAST_INSERT_ID()");


		# grab tags autmatically from exif data and other attributes			
		my @months = qw(january february march april may june july august september october november december);
		my @weekdays = qw(sunday monday tuesday wednesday thursday friday saturday);
		my $monthname = $months[$mon-1];
		my $dayname = $weekdays[$wday];
		my $weekend = 0;
		$weekend = 1 if (($wday == 0) or ($wday == 6));
		my ($w,$h) = getImageSize("$CONF{STOREDIR}/$path");
		my $ratio = 0;
		my $shortside = 0;
		$h = 1 if ($h == 0); # don't allow division by zero
		$w = 1 if ($w == 0); # don't allow division by zero
		if ($w > $h) {
			$ratio = $w / $h;
			$shortside = $h;
		} else {
			$ratio = $h / $w;
			$shortside = $w;
		}
		$model =~ s/ //g;
		addTags($num, $tag) if ($tag ne "");
		addTags($num, $year, $monthname, $dayname, 'ISO' . $speed, $model);
		if ($weekend) {
			addTags($num, 'weekend');
		} else {
			addTags($num, 'weekday');
		}
		addTags($num, 'longexposure') if ($exposure_integer > 2);
		addTags($num, 'telephoto') if ($focal > 99);
		addTags($num, 'wideangle') if (($focal < 40) and ($focal > 0));
		addTags($num, '3:2') if (($ratio >= 1.45) and ($ratio <= 1.55));
		addTags($num, '1:1 square') if (($ratio >= 1) and ($ratio <= 1.05));
		addTags($num, '5:4') if (($ratio >= 1.15) and ($ratio <= 1.25));
		addTags($num, '4:3') if (($ratio >= 1.3) and ($ratio <= 1.35));
		# resolution lo / med / high / 480 / 720 / 1080 based on short dimension of image
	
		# add user-supplied tags
		if (exists $p->{uc "TAGS_$md5"}) {
			addTags($num, $p->{uc "TAGS_$md5"});
		}
		
		# populate exif data
		my $exif = ImageInfo("$CONF{STOREDIR}/$path");
		while (my ($name,$value) = each %$exif) {
			#print "$name = $value<br>\n";
			DB_Do($dbh,"INSERT INTO exif (image,name,value) VALUES ($num,'$name','$value')");
		}
	return 1;
}

sub form_Import {
	my $p = shift;

	print "<br><br>\nThe following files are ready to be imported. Any tags to add?<br>\n";
	print "<a href=\"$CONF{SCRIPTURL}?action=importform&removedupes=1\">Remove duplicates from import directory</a><br><br>\n";
	print "<form method=\"POST\" action=\"$CONF{SCRIPTURL}\"><input type=\"hidden\" name=\"action\" value=\"import\"><input type=\"text\" name=\"tag\" size=\"40\"><input type=\"submit\" value=\"Import!\"><br><br>\n";

	opendir(DIR,$CONF{'IMPORTDIR'}) or warn "Could not open import directory: $!";
	my $count = 0;
	my $total = 0;
	my $remove_dupes = 0;
	$remove_dupes = 1 if ($p->{'REMOVEDUPES'} == 1);
	my @tmp;
	my @filelist;
	while (my $file = readdir(DIR)) {
		next if ($file =~ /^\./);
		next unless ($file =~ /\.jpg$/i); # only import images!
		push @tmp, $file;
	}
	@filelist = sort @tmp;
	$total = $#filelist + 1;
	print "$total images in import directory<br><br>\n";
	print "<table>\n";
	for (my $i = 0; $i <= $#filelist; $i++) {
		my $file = $filelist[$i];
		# resize big images
		my ($w,$h) = getImageSize("$CONF{IMPORTDIR}/$file");
		if (($w > $CONF{IMAGESIZE}) or ($h > $CONF{'IMAGESIZE'})) {
			print "Resizing $file ($w x $h) ...<br>\n";
			resize("$CONF{IMPORTDIR}/$file","$CONF{IMPORTDIR}/$file.tmp",$CONF{'IMAGESIZE'},$CONF{'IMAGESIZE'});
			rename "$CONF{IMPORTDIR}/$file", "$CONF{IMPORTDIR}/$file.orig";
			rename "$CONF{IMPORTDIR}/$file.tmp", "$CONF{IMPORTDIR}/$file";
		}

		my $md5 = md5("$CONF{IMPORTDIR}/$file");
		my ($duplicate) = DB_GetRow($dbh, "SELECT Count(1) FROM images WHERE md5='$md5'");
		my $subdir = substr($md5,0,2);
		mkdir "$CONF{STOREDIR}/$subdir" unless ( -f "$CONF{STOREDIR}/$subdir");
		# create thumbnail
		resize("$CONF{IMPORTDIR}/$file","$CONF{STOREDIR}/$subdir/tn_$md5.jpg",$CONF{'TNSIZE'},$CONF{'TNSIZE'}) if (! (-f "$CONF{STOREDIR}/$subdir/tn_$md5.jpg"));
		if ($duplicate) {
			if ($remove_dupes) {
				unlink "$CONF{IMPORTDIR}/$file";
				print "<tr><td><img src=\"$CONF{WEBSTORE}/$subdir/tn_$md5.jpg\"></td><td><b>$file - removed as duplicate</b></td></tr>\n";
				$count -= 1;
			} else {
				print "<tr><td><img src=\"$CONF{WEBSTORE}/$subdir/tn_$md5.jpg\"></td><td><b>$file - already indexed</b></td></tr>\n";
			}
		} else {
			print "<tr><td><img src=\"$CONF{WEBSTORE}/$subdir/tn_$md5.jpg\"></td><td>$file ";
			print "<input id=\"tags_$md5\" name=\"tags_$md5\" size=\"16\">\n";
			print "</td></tr>\n";
		}
		$count += 1;
		last if ($count == $CONF{'IMPORTLIMIT'});
	}
	print "</table>\n</form><br><br>\n";
	closedir(DIR);

}

sub form_Upload {
	print "<br><br>\n";
	print "<form action=\"$CONF{SCRIPTURL}\" method=\"POST\" enctype=\"multipart/form-data\">\n";
	print "<input type=\"hidden\" name=\"action\" value=\"upload\">\n";
	print "<input name=\"imagefile\" id=\"imagefile\" type=\"file\"><br>\n";
	print "Tags for this image: <input name=\"tag\" id=\"tag\" type=\"text\"><br>\n";
	print "<input type=\"submit\" value=\"Upload!\"></form>\n";
}

sub ajax_countView {
	my $p = shift;
	my $num = $p->{'FILE'};
	countView($num);
}

sub ajax_imageInfo {
	my $ref = shift;
	my ($num,$path,$md5,$filename,$taken,$imported) = @$ref;

	my $fileinfo = return_fileInfo($num,$path,$filename);
	print $fileinfo;
	return 1;
}

sub ajax_imageTags {
	my $ref = shift;
	my ($num,$path,$md5,$filename,$taken,$imported) = @$ref;

	my $fileinfo = return_tagLinks($num,$path,$filename);
	print $fileinfo;
	return 1;
}

sub return_fileInfo {
	my $num = shift;
	my $path = shift;
	my $filename = shift;
	my $fileinfo = "";
	if ($CONF{'EXIF'}) {
		my ($uploaded) = DB_GetRow($dbh,"SELECT imported FROM images WHERE num=$num");
		$uploaded = scalar localtime($uploaded);
		my ($date,$time,$aperture,$exposure,$speed,$focal,$model) = exifInfo("$CONF{STOREDIR}/$path");
		if ($speed ne "") {
			$fileinfo .= "<br><b>$filename</b><br><br>\n\n$date $time <br>\n$exposure sec @ $aperture <br>\nISO$speed <br>\nFocal Length $focal";
			$fileinfo .= "<br><i>$model</i><br><br>uploaded $uploaded";
		}
	}
	return $fileinfo;
}

sub return_tagLinks {
	my $num = shift;
	my $path = shift;
	my $filename = shift;
	my $fileinfo = "";

	my ($views) = DB_GetRow($dbh, "SELECT Count(1) FROM views WHERE image=$num");
	$fileinfo .= "<br>\n<b>Views:</b> $views<br>\n";
	my $tags = "";
	my $tagref = DB_GetAll_Ref($dbh,"SELECT tag FROM tags WHERE image=$num");
	for (my $i = 0; $i < (scalar @$tagref); $i++) {
		my $tag = $tagref->[$i][0];
		if ($CONF{'ISADMIN'}) {
			$tags .= " <a href=\"$CONF{SCRIPTURL}?tags=$tag\">$tag</a> <a onclick=\"webGet('$CONF{SCRIPTURL}?action=ajax_removetag&file=$num&tag=$tag'); document.getElementById('fileinfo').innerHTML=webGet('$CONF{SCRIPTURL}?action=ajax_imagetags&file='+imageList[idx])\" style=\"color: red; cursor:pointer;\">x</a>,";
		} else {
			$tags .= " <a href=\"$CONF{SCRIPTURL}?tags=$tag\">$tag</a>,";
		}
	}
	$tags =~ s/,$//;
	$fileinfo .= "<br><br>\n<b>Tags:</b> $tags";
	return $fileinfo;
}

sub ajax_Highlight {
	my $p = shift;
	my $tag = $p->{'HIGHLIGHT'};
	$tag =~ s/\%20/ /g;
	$tag =~ s/\'//g;
	$tag = lc $tag;
	DB_Do($dbh,"INSERT INTO configuration (name,value) VALUES ('highlight','$tag')");

	return 1;
}

sub ajax_unHighlight {
	my $p = shift;
	my $tag = $p->{'HIGHLIGHT'};
	$tag =~ s/\%20/ /g;
	$tag =~ s/\'//g;
	$tag = lc $tag;
	DB_Do($dbh,"DELETE FROM configuration WHERE name='highlight' AND value='$tag'");

	return 1;
}

sub ajax_addTags {
	my $p = shift;
	my $file = $p->{'FILE'};
	my $string = $p->{'TAGS'};
	$string =~ s/\%20/ /g;
	$string =~ s/\'//g;
	my @tags = split(/ /, $string);
	foreach my $tag (@tags) {
		$tag =~ s/,//g;
		$tag = lc $tag;
		DB_Do($dbh,"INSERT INTO tags (image,tag) VALUES ($file,'$tag')");
	}
	return 1;
}

sub ajax_removeTag {
		my $p = shift;
		my $file = $p->{'FILE'};
		my $tag = $p->{'TAG'};
		my $strsql = "DELETE FROM tags WHERE image=$file AND tag='$tag'";
		#warn $strsql;
		DB_Do($dbh,$strsql);
		return 1;
}

sub ajax_makeThumb {
	my $p = shift;
	my $file = $p->{'FILE'};

	my ($num,$path,$md5,$filename,$taken,$uploaded) = DB_GetRow($dbh, "SELECT num,path,md5,filename,taken,imported FROM images WHERE num=$file");
	my $subdir = substr($md5,0,2);
	my $thumb = "tn_$md5.jpg";

	#warn "creating thumbnail $thumb for $path";
	# does the thumbnail exist?
	if (! (-f "$CONF{STOREDIR}/$subdir/$thumb")) {
		# create the thumbnail
		#print STDERR "Creating thumbnail for $file, $md5\n";
		resize("$CONF{STOREDIR}/$path","$CONF{STOREDIR}/$subdir/$thumb",$CONF{'TNSIZE'},$CONF{'TNSIZE'});
	}

	return 1;
}

sub ajax_exif {
	my $p = shift;
	my $num = $p->{'FILE'};

	my $ref_exif = DB_GetAll_Ref($dbh,"SELECT name,value FROM exif WHERE image=$num ORDER BY name");
	my $exifdata = "";
	for (my $i = 0; $i < (scalar @$ref_exif); $i++) {
		my $name = $ref_exif->[$i][0];
		my $value = $ref_exif->[$i][1];
		next if ($name eq "Directory");
		next if ($name eq "ThumbnailImage");
		next if ($name eq "FilePermissions");
		$exifdata .= sprintf("%s: %s\n", $name, $value);
	}
	print $exifdata;
}

sub addTags {
	my $num = shift;
	while (my $tag = shift) {
		$tag =~ s/,//g;
		$tag =~ s/[\'\"\`]//g; # no quotes allowed
		my @words = split(/ /, $tag);
		foreach my $word (@words) {
			$word = lc $word;
			#DB_Do($dbh,"INSERT INTO tags (image,tag) VALUES ($num,'$word')");
			DB_Do($dbh,"REPLACE INTO tags (image,tag) VALUES ($num,'$word')");
		}
	}
	return 1;
}

sub drawTags {
	my $p = shift;
	# get unique tag values, display the most frequently used
	my ($images) = DB_GetRow($dbh, "SELECT Count(1) FROM images");
	my $total = 0; my $max = 0;
	my $hash = {};
	my $tagref = DB_GetAll_Ref($dbh,"SELECT DISTINCT tag FROM tags");
	my %temporal;
	my @tmp = qw(january february march april may june july august september october november december sunday monday tuesday wednesday thursday friday saturday);
	foreach my $value (@tmp) { $temporal{$value} = 1; }
	for (my $i = 1990; $i <= 2025; $i++) {
		$temporal{$i} = 1;
	}
	for (my $i = 0; $i < (scalar @$tagref); $i++) {
		my $tag = $tagref->[$i][0];
		my ($count) = DB_GetRow($dbh, "SELECT Count(1) FROM tags WHERE tag='$tag'");
		#print "$tag: $count<br>\n";
		if (exists $temporal{$tag}) {
			$hash->{temporal}{$tag} = $count;
		} else {
			$hash->{other}{$tag} = $count;
		}
		$total += $count;
		$max = $count if ($count > $max);
	}

	print "<br><br>\n";
	print "<form method=\"GET\" action=\"$CONF{SCRIPTURL}\">Search: <input type=\"text\" name=\"tags\" size=\"40\"><input type=\"submit\" value=\"Search!\"><br><span style=\"font-size:9px; font-style:italics\">images will only be shown if they have ALL tags specified</span></form><br><br>\n";

	print "<h2>Common tags:</h2>\n";
	my $bigsize = 64;
	my @sorted = sort { $a cmp $b } keys %{$hash->{other}};
	my $tags = $#sorted;
	for (my $i = 0; $i <= $#sorted; $i++) {
		my $tag = $sorted[$i];
		my $count = $hash->{other}{$tag};
		my $size = sprintf("%d", log($count)/log($max) * $bigsize);
		$size = 11 if ($size < 11);
		print "<span style=\"font-size: " . $size . "px;\"><a href=\"$CONF{SCRIPTURL}?tags=$tag\">$tag </a></span>\n";
		$size -= 1 if ($size > 8);
	}
	@sorted = sort { $a cmp $b } keys %{$hash->{temporal}};
	$tags += $#sorted;
	print "<h2>Time-based tags:</h2>\n";
	print "<span style=\"font-size: 11px;\">";
	for (my $i = 0; $i <= $#sorted; $i++) {
		my $tag = $sorted[$i];
		print "<a href=\"$CONF{SCRIPTURL}?tags=$tag\">$tag </a>\n";
	}
	print "</span>";
	print "<br><br>\n$images images, $tags tags.<br><br>\n";
}

sub drawToolbar {
	print "<div style=\"z-index:10; display:inline; position:fixed; top:0px; left:0px; right:0px; height:2em; font-size: 18px; background-color: $CONF{CLR_IMGBG}\">\n";
	print "<div style=\"position:relative; display:inline; top:0.5em; margin-left: 25px;\">\n";
	printf("<a href=\"%s\">All</a> | <a href=\"%s\">Search</a> | <a href=\"%s\">Recent</a>", "$CONF{SCRIPTURL}?tags=", "$CONF{SCRIPTURL}?action=showtags", "$CONF{SCRIPTURL}?tags=recent");
	printf(" | <a href=\"%s\">Import</a> | <a href=\"%s\">Upload</a>", "$CONF{SCRIPTURL}?action=importform", "$CONF{SCRIPTURL}?action=uploadform") if ($CONF{'ISADMIN'});
	#printf(" | <a href=\"%s\" style=\"color:red\">Admin</a>\n", $CONF{SCRIPTURL} . "?action=admin") if ($CONF{'ISADMIN'});
	printf(" | [%s]", $ENV{'REMOTE_ADDR'});
	print "</div>\n";
	print "</div>\n"; 
}


